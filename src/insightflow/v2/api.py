import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, Response
from dotenv import dotenv_values
from insightflow.v2.config import V2Settings
from insightflow.v2.contracts import ChatInput
from insightflow.v2.errors import Fault
from insightflow.v2.store import TERMINAL
from insightflow.v2.service import Runtime


def load_settings():
    # Deliberate local configuration loading; environment overrides ignored file values.
    values = {**dotenv_values(Path(".env")), **os.environ}
    kwargs = {
        k[len("INSIGHTFLOW_V2_") :].lower(): v
        for k, v in values.items()
        if k.startswith("INSIGHTFLOW_V2_") and v is not None
    }
    if "auth_tokens" in kwargs and isinstance(kwargs["auth_tokens"], str):
        kwargs["auth_tokens"] = json.loads(kwargs["auth_tokens"])
    kwargs.setdefault("reader_url", values.get("INSIGHTFLOW_DATABASE_URL", ""))
    kwargs.setdefault("api_key", values.get("DEEPSEEK_API_KEY", ""))
    return V2Settings(**kwargs)


def create_app(settings=None, provider=None):
    @asynccontextmanager
    async def lifespan(app):
        s = settings or load_settings()
        app.state.runtime = await asyncio.to_thread(Runtime, s, provider)
        await app.state.runtime.start()
        try:
            yield
        finally:
            await app.state.runtime.close()

    app = FastAPI(title="InsightFlow V2", version="0.2.0", lifespan=lifespan)

    @app.exception_handler(Fault)
    async def fault_handler(request, exc):
        from fastapi.responses import JSONResponse

        code = (
            404
            if exc.code == "NOT_FOUND"
            else 409
            if exc.code == "IDEMPOTENCY_CONFLICT"
            else 429
            if exc.code in ("OVERLOADED", "QUEUE_TIMEOUT")
            else 503
        )
        return JSONResponse(status_code=code, content={"error": exc.public()})

    async def principal(request: Request):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise HTTPException(401, "Bearer authentication required")
        token = auth[7:]
        found = None
        if len(token) > 512:
            raise HTTPException(401, "Invalid credentials")
        for secret, name in request.app.state.runtime.s.auth_tokens.items():
            if hmac.compare_digest(token, secret):
                found = name
        if found is None:
            raise HTTPException(401, "Invalid credentials")
        return found

    def rid(value):
        try:
            return str(UUID(value))
        except ValueError:
            raise HTTPException(404, "Run not found") from None

    def public(row):
        return {
            k: str(row[k]) if k == "run_id" else row[k]
            for k in ("run_id", "session_id", "status", "error_code", "result")
        }

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "v2"}

    @app.get("/ready")
    async def ready(request: Request):
        rt = request.app.state.runtime
        if rt.closing:
            raise HTTPException(503, "Shutting down")

        def probe():
            with rt.store.pool.connection() as c:
                c.execute("SELECT 1")
            with rt.executor.pool.connection() as c:
                c.execute("SELECT 1")

        try:
            await asyncio.wait_for(asyncio.to_thread(probe), 3)
        except Exception:
            raise HTTPException(503, "Dependencies unavailable") from None
        return {"status": "ready", "mode": rt.s.mode}

    @app.get("/metrics")
    async def metrics(request: Request, user=Depends(principal)):
        return Response(request.app.state.runtime.telemetry.render(), media_type="text/plain; version=0.0.4")

    @app.post("/v2/runs", status_code=202)
    async def submit(body: ChatInput, request: Request, user=Depends(principal)):
        row, replayed = await request.app.state.runtime.submit(user, body)
        return {**public(row), "replayed": replayed}

    @app.post("/v2/chat")
    async def chat(body: ChatInput, request: Request, user=Depends(principal)):
        rt = request.app.state.runtime
        row, replayed = await rt.submit(user, body)
        run_id = str(row["run_id"])
        try:
            while row["status"] not in TERMINAL:
                if await request.is_disconnected():
                    await rt.cancel(run_id, user)
                    raise HTTPException(499, "Client disconnected")
                await asyncio.sleep(0.025)
                row = await asyncio.to_thread(rt.store.get, run_id, user)
        except asyncio.CancelledError:
            await asyncio.shield(rt.cancel(run_id, user))
            raise
        return {**public(row), "replayed": replayed}

    @app.get("/v2/runs/{run_id}")
    async def get_run(run_id: str, request: Request, user=Depends(principal)):
        return public(await asyncio.to_thread(request.app.state.runtime.store.get, rid(run_id), user))

    @app.get("/v2/runs/{run_id}/trace")
    async def trace_run(run_id: str, request: Request, user=Depends(principal)):
        rt = request.app.state.runtime
        run_id = rid(run_id)
        await asyncio.to_thread(rt.store.get, run_id, user)
        return {
            "run_id": run_id,
            "spans": rt.telemetry.exporter.for_run(run_id),
            "scope": "bounded process-local OTel SDK spans; persistent events remain in PostgreSQL",
        }

    @app.post("/v2/runs/{run_id}/cancel")
    async def cancel(run_id: str, request: Request, user=Depends(principal)):
        rt = request.app.state.runtime
        run_id = rid(run_id)
        await rt.cancel(run_id, user)
        return public(await asyncio.to_thread(rt.store.get, run_id, user))

    @app.get("/v2/sessions/{session_id}")
    async def session(session_id: str, request: Request, user=Depends(principal)):
        return await asyncio.to_thread(request.app.state.runtime.store.session, session_id, user)

    @app.get("/v2/runs/{run_id}/events")
    async def events(run_id: str, request: Request, after: int = 0, user=Depends(principal)):
        rt = request.app.state.runtime
        run_id = rid(run_id)
        await asyncio.to_thread(rt.store.get, run_id, user)

        async def stream():
            cursor = max(0, after)
            try:
                while True:
                    if await request.is_disconnected():
                        await rt.cancel(run_id, user)
                        return
                    rows = await asyncio.to_thread(rt.store.events, run_id, user, cursor)
                    for event in rows:
                        cursor = event["event_id"]
                        yield (
                            "id: "
                            + str(cursor)
                            + "\nevent: "
                            + event["stage"]
                            + "\ndata: "
                            + json.dumps(
                                {"run_id": run_id, "stage": event["stage"], "details": event["payload"]},
                                ensure_ascii=False,
                            )
                            + "\n\n"
                        )
                    row = await asyncio.to_thread(rt.store.get, run_id, user)
                    if row["status"] in TERMINAL:
                        # Only authoritative persisted terminal state emits answer; failed never does.
                        yield "event: final\ndata: " + json.dumps(public(row), ensure_ascii=False) + "\n\n"
                        return
                    yield ": heartbeat\n\n"
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                await asyncio.shield(rt.cancel(run_id, user))
                raise

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/", response_class=HTMLResponse)
    async def page():
        return (Path(__file__).with_name("demo.html")).read_text()

    return app


app = create_app()
