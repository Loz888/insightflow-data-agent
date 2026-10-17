import asyncio
import time
from contextlib import suppress
from uuid import uuid4
from datetime import datetime, timezone
from insightflow.config import Settings
from insightflow.database.executor import ReadonlyExecutor
from insightflow.v2.errors import Fault
from insightflow.v2.store import Store, TERMINAL
from insightflow.v2.retrieval import Retriever
from insightflow.v2.telemetry import Telemetry
from insightflow.v2.tools import Registry
from insightflow.v2.provider import AsyncDeepSeek, RequestBudget
from insightflow.v2.mock import OfflineProvider
from insightflow.v2.graph import build_graph


class Runtime:
    def __init__(self, settings, provider=None):
        self.s = settings
        self.owner = str(uuid4())
        self.telemetry = Telemetry()
        self.store = Store(settings.runtime_url.get_secret_value())
        self.retriever = Retriever(settings.reader_url.get_secret_value())
        self.executor = ReadonlyExecutor(
            Settings(
                database_url=settings.reader_url,
                pool_size=settings.db_concurrency if settings.db_concurrency <= 4 else 4,
            ),
            self.retriever.tables,
        )
        self.registry = Registry(self.retriever, self.executor, settings, self.telemetry)
        self.provider = provider or (
            AsyncDeepSeek(settings, self.store, self.telemetry)
            if settings.mode == "deepseek"
            else OfflineProvider(settings.reference_time)
        )
        self.graph = build_graph(self.provider, self.registry, settings, self.store, self.telemetry)
        self.tasks = {}
        self.closing = False
        self.reaper = None

    async def start(self):
        await asyncio.to_thread(self.store.recover)
        self.reaper = asyncio.create_task(self._reap())

    async def _reap(self):
        while True:
            await asyncio.sleep(self.s.lease_seconds)
            try:
                await asyncio.to_thread(self.store.recover)
            except Exception:
                pass  # API readiness independently checks availability; no secret logging.

    async def submit(self, principal, body):
        if self.closing:
            raise Fault("SHUTTING_DOWN")
        # Replays must work even when overloaded; only new work consumes admission capacity.
        row, created = await asyncio.to_thread(
            self.store.enqueue, principal, body, self.s.request_seconds, self.s.idempotency_ttl_seconds
        )
        rid = str(row["run_id"])
        if created:
            if len(self.tasks) >= self.s.active_limit:
                await asyncio.to_thread(
                    self.store.complete, rid, principal, self.owner, "failed", None, None, None, "OVERLOADED"
                )
                raise Fault("OVERLOADED", "服务已满，请稍后重试；新幂等键才创建新尝试。")
            self.tasks[rid] = asyncio.create_task(self._run(row))
            self.tasks[rid].add_done_callback(lambda task, key=rid: self.tasks.pop(key, None))
        return await asyncio.to_thread(self.store.get, rid, principal), not created

    async def _heartbeat(self, row, task):
        while True:
            await asyncio.sleep(min(0.25, self.s.lease_seconds / 3))
            try:
                cancelled = await asyncio.to_thread(
                    self.store.heartbeat, str(row["run_id"]), self.owner, self.s.lease_seconds
                )
                if cancelled:
                    task.cancel()
                    return
            except Exception:
                task.cancel()
                return

    async def _run(self, row):
        rid = str(row["run_id"])
        principal = row["principal"]
        heartbeat = None
        span_scope = self.telemetry.tracer.start_as_current_span("run", attributes={"run.id": rid})
        run_span = span_scope.__enter__()
        self.telemetry.active.inc()
        started = time.perf_counter()
        session = None
        status = "failed"
        error = None
        budget = RequestBudget(
            rid, time.monotonic() + max(0, (row["deadline"] - datetime.now(timezone.utc)).total_seconds())
        )
        try:
            async with asyncio.timeout(budget.remaining()):
                queue_started = time.monotonic()
                while session is None:
                    run = await asyncio.to_thread(self.store.get, rid, principal)
                    if run["status"] in TERMINAL:
                        return
                    session = await asyncio.to_thread(
                        self.store.claim, rid, principal, self.owner, self.s.lease_seconds
                    )
                    if session is None:
                        if time.monotonic() - queue_started > self.s.queue_seconds:
                            raise Fault("QUEUE_TIMEOUT", "同会话排队超时。")
                        await asyncio.sleep(0.03)
                self.telemetry.seconds.labels("session_queue").observe(time.monotonic() - queue_started)
                heartbeat = asyncio.create_task(self._heartbeat(row, asyncio.current_task()))
                state = {
                    "question": row["question"],
                    "previous": session["constraints"],
                    "run_id": rid,
                    "source": self.provider.source,
                    "budget": budget,
                    "tool_results": [],
                    "evidence_by_period": {},
                    "repairs": 0,
                    "compared": False,
                }
                result = await self.graph.ainvoke(state, {"recursion_limit": self.s.max_graph_steps})
                output = {
                    **result["output"],
                    "usage": budget.usage(),
                    "decisions": budget.decisions,
                    "model": self.s.model if self.provider.source == "model" else "offline-rules",
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "run_id": rid,
                }
                if output["disposition"] == "answer":
                    plan = result["plan"].model_dump(mode="json")
                else:
                    plan = None
                ok = await asyncio.to_thread(
                    self.store.complete,
                    rid,
                    principal,
                    self.owner,
                    "succeeded",
                    output,
                    plan,
                    session["version"],
                )
                final = await asyncio.to_thread(self.store.get, rid, principal)
                status = final["status"] if ok else "failed"
        except asyncio.CancelledError:
            status = "cancelled"
            error = "CANCELLED" if not self.closing else "SHUTDOWN"
        except TimeoutError:
            error = "DEADLINE"
        except Fault as exc:
            error = exc.code
        except Exception:
            error = "INTERNAL_ERROR"  # raw DB/HTTP exceptions are never logged or returned.
        finally:
            if heartbeat:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            if status != "succeeded":
                try:
                    await asyncio.shield(
                        asyncio.to_thread(
                            self.store.complete,
                            rid,
                            principal,
                            self.owner,
                            status,
                            {"usage": budget.usage(), "decisions": budget.decisions},
                            None,
                            None,
                            error,
                        )
                    )
                except Exception:
                    pass  # expired lease is recovered by reaper, never bypass fencing.
            if error:
                from opentelemetry.trace import StatusCode

                run_span.set_status(StatusCode.ERROR, error)
            span_scope.__exit__(None, None, None)
            self.telemetry.active.dec()
            self.telemetry.requests.labels(status).inc()
            self.telemetry.seconds.labels("run").observe(time.perf_counter() - started)

    async def wait(self, rid, principal):
        while True:
            row = await asyncio.to_thread(self.store.get, rid, principal)
            if row["status"] in TERMINAL:
                return row
            await asyncio.sleep(0.025)

    async def cancel(self, rid, principal):
        await asyncio.to_thread(self.store.cancel, rid, principal)
        task = self.tasks.get(str(rid))
        if task:
            task.cancel()

    async def close(self):
        self.closing = True
        if self.reaper:
            self.reaper.cancel()
            with suppress(asyncio.CancelledError):
                await self.reaper
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.provider.close()
        await asyncio.to_thread(self.executor.close)
        await asyncio.to_thread(self.store.close)
        self.telemetry.trace_provider.shutdown()
