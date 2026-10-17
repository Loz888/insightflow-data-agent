"""Controlled delayed Mock + real HTTP/PG. Not a model capability benchmark."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import signal
from pathlib import Path
from uuid import uuid4
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-loopback-fault-token-only"


def serve():
    import uvicorn
    from insightflow.v2.api import create_app
    from insightflow.v2.config import V2Settings
    from insightflow.v2.mock import OfflineProvider

    d = dotenv_values(ROOT / ".env")
    s = V2Settings(
        runtime_url=d["INSIGHTFLOW_V2_TEST_RUNTIME_URL"],
        reader_url=d["INSIGHTFLOW_TEST_DATABASE_URL"],
        auth_tokens={TOKEN: "fault-test"},
        active_limit=2,
        request_seconds=1,
        queue_seconds=0.2,
    )

    class Delayed(OfflineProvider):
        async def request(self, task, payload, schema, budget):
            if task == "plan":
                await asyncio.sleep(2)
            return await super().request(task, payload, schema, budget)

    uvicorn.run(
        create_app(s, Delayed(s.reference_time)),
        host="127.0.0.1",
        port=18524,
        log_level="warning",
        access_log=False,
    )


async def checks(out):
    records = []
    from insightflow.v2.store import Store

    store = Store(dotenv_values(ROOT / ".env")["INSIGHTFLOW_V2_TEST_RUNTIME_URL"])
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:18524", timeout=5, headers={"Authorization": "Bearer " + TOKEN}
    ) as c:
        for _ in range(100):
            try:
                if (await c.get("/ready")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Fault server not ready")

        def body(sid=None):
            return {
                "session_id": sid or uuid4().hex,
                "question": "2026年9月订单数是多少？",
                "idempotency_key": uuid4().hex,
            }

        async def terminal(rid):
            for _ in range(100):
                row = (await c.get("/v2/runs/" + rid)).json()
                if row.get("status") in ("cancelled", "failed", "succeeded", "interrupted"):
                    return row
                await asyncio.sleep(0.03)
            raise RuntimeError("Run did not terminate")

        # Timeout before response headers creates a real HTTP disconnect.
        request = body()
        try:
            await c.post("/v2/chat", json=request, timeout=0.05)
        except httpx.ReadTimeout:
            pass
        rid = None
        for _ in range(100):
            with store.pool.connection() as conn:
                row = conn.execute(
                    "SELECT run_id,status FROM agent_runtime.runs WHERE principal=%s AND idempotency_key=%s",
                    ("fault-test", request["idempotency_key"]),
                ).fetchone()
            if row and row["status"] == "cancelled":
                rid = str(row["run_id"])
                break
            await asyncio.sleep(0.03)
        if rid is None:
            raise RuntimeError("Client disconnect did not cancel run")
        records.append({"scenario": "HTTP client disconnect", "status": "PASS", "run_id": rid})
        # Closing a live SSE connection must cancel its run, never emit a success after failure.
        row = (await c.post("/v2/runs", json=body())).json()
        rid = row["run_id"]
        async with c.stream("GET", "/v2/runs/" + rid + "/events") as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    break
        result = await terminal(rid)
        if result["status"] != "cancelled":
            raise RuntimeError("SSE disconnect did not cancel")
        records.append({"scenario": "SSE disconnect", "status": "PASS", "run_id": rid})
        first = (await c.post("/v2/runs", json=body())).json()
        second = (await c.post("/v2/runs", json=body())).json()
        res = await c.post("/v2/runs", json=body())
        if res.status_code != 429:
            raise RuntimeError("Expected overload response")
        records.append(
            {"scenario": "admission backpressure", "status": "PASS", "http_status": res.status_code}
        )
        for row in (first, second):
            await c.post("/v2/runs/" + row["run_id"] + "/cancel")
            await terminal(row["run_id"])
        sid = uuid4().hex
        first = (await c.post("/v2/runs", json=body(sid))).json()
        second = (await c.post("/v2/runs", json=body(sid))).json()
        result = await terminal(second["run_id"])
        if result["error_code"] != "QUEUE_TIMEOUT":
            raise RuntimeError("Expected bounded same-session queue wait")
        await c.post("/v2/runs/" + first["run_id"] + "/cancel")
        await terminal(first["run_id"])
        records.append({"scenario": "queue timeout", "status": "PASS"})
        row = (await c.post("/v2/chat", json=body())).json()
        if row["error_code"] != "DEADLINE" or row["status"] != "failed":
            raise RuntimeError("Expected total deadline")
        if (await c.get("/ready")).status_code != 200:
            raise RuntimeError("Resources not released")
        records.append({"scenario": "request deadline and resource reuse", "status": "PASS"})
    store.close()
    (out / "results.json").write_text(
        json.dumps(
            {
                "model": "controlled delayed Mock; no paid call",
                "entry": "real loopback HTTP + real PostgreSQL",
                "scenarios": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    return records


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--serve", action="store_true")
    p.add_argument("--output")
    args = p.parse_args()
    if args.serve:
        return serve()
    out = Path(args.output)
    out.mkdir(exist_ok=False, parents=True)
    env = dict(os.environ)
    env.pop("DEEPSEEK_API_KEY", None)
    env["INSIGHTFLOW_V2_MODE"] = "mock"
    env["INSIGHTFLOW_V2_LIVE_ENABLED"] = "false"
    proc = subprocess.Popen(
        [sys.executable, __file__, "--serve"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        print(json.dumps(asyncio.run(checks(out)), ensure_ascii=False))
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


if __name__ == "__main__":
    main()
