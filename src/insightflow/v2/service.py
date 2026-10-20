import asyncio
import time
from contextlib import suppress
from uuid import uuid4
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
from insightflow.v2.versions import WORKFLOW_VERSION


class Runtime:
    def __init__(self, settings, provider=None, tenant=None):
        if settings.profile == "internal-pilot" and tenant not in settings.pilot_tenants:
            raise ValueError("server-registered pilot tenant required")
        self.tenant = tenant
        self.s = settings
        self.owner = str(uuid4())
        self.telemetry = Telemetry()
        self.store = Store(
            settings.runtime_url.get_secret_value(), namespace_sessions=settings.profile == "internal-pilot"
        )
        if settings.mode == "deepseek":
            ledger = self.store.budget(settings.experiment_id)
            if ledger is None:
                self.store.close()
                raise ValueError(
                    "Live requires an existing explicitly authorised durable experiment ledger; a new database must not reset project spending"
                )
        self.retriever = Retriever(settings.reader_url.get_secret_value())
        if tenant is not None:
            from insightflow.database.connection import checked_connection

            with checked_connection(settings.reader_url.get_secret_value()) as c:
                for table in self.retriever.tables:
                    row = c.execute(
                        "SELECT c.relrowsecurity,c.relforcerowsecurity,pg_get_userbyid(c.relowner)=current_user FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='business' AND c.relname=%s",
                        (table,),
                    ).fetchone()
                    policies = c.execute(
                        "SELECT polname,pg_get_expr(polqual,polrelid) FROM pg_policy WHERE polrelid=('business.' || %s)::regclass AND polcmd IN ('*','r')",
                        (table,),
                    ).fetchall()
                    if (
                        not row
                        or not row[0]
                        or not row[1]
                        or row[2]
                        or len(policies) != 1
                        or policies[0][0] != "pilot_tenant"
                        or "insightflow.tenant_id" not in policies[0][1]
                    ):
                        self.store.close()
                        raise ValueError("Pilot requires audited FORCE RLS on every authorized table")
        self.executor = ReadonlyExecutor(
            Settings(
                database_url=settings.reader_url,
                tenant_id=tenant,
                pool_size=settings.db_concurrency if settings.db_concurrency <= 4 else 4,
            ),
            self.retriever.tables,
        )
        self.registry = Registry(self.retriever, self.executor, settings, self.telemetry)
        self.provider = provider or (
            AsyncDeepSeek(settings, self.store, self.telemetry, tenant=tenant)
            if settings.mode == "deepseek"
            else OfflineProvider(settings.reference_time)
        )
        self.graph = build_graph(self.provider, self.registry, settings, self.store, self.telemetry)
        self.checkpoint_pool = None
        self.saver = None
        self.tasks = {}
        self.principals = {}
        self.closing = False
        self.reaper = None

    async def start(self):
        if self.s.profile == "internal-pilot":
            from insightflow.v2.checkpoints import open_saver

            self.checkpoint_pool, self.saver = await open_saver(self.s.runtime_url.get_secret_value())

            async def guard(rid):
                await asyncio.to_thread(self.store.assert_owner, rid, self.owner)

            self.graph = build_graph(
                self.provider, self.registry, self.s, self.store, self.telemetry, self.saver, guard
            )
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
        local_deadline = time.monotonic() + self.s.request_seconds
        row, created = await asyncio.to_thread(
            self.store.enqueue, principal, body, self.s.request_seconds, self.s.idempotency_ttl_seconds
        )
        rid = str(row["run_id"])
        if created:
            row["_local_deadline"] = local_deadline
            if len(self.tasks) >= self.s.active_limit:
                await asyncio.to_thread(
                    self.store.complete, rid, principal, self.owner, "failed", None, None, None, "OVERLOADED"
                )
                raise Fault("OVERLOADED", "服务已满，请稍后重试；新幂等键才创建新尝试。")
            self.principals[rid] = principal
            self.tasks[rid] = asyncio.create_task(self._run(row))

            def completed(task, key=rid):
                self.tasks.pop(key, None)
                self.principals.pop(key, None)

            self.tasks[rid].add_done_callback(completed)
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
        budget = RequestBudget(rid, row.get("_local_deadline", time.monotonic() + self.s.request_seconds))
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
                    "workflow_version": WORKFLOW_VERSION,
                    "tool_results": [],
                    "evidence_by_period": {},
                    "repairs": 0,
                    "compared": False,
                }
                from insightflow.v2.checkpoints import CURRENT_BUDGET

                budget_context = CURRENT_BUDGET.set(budget)
                try:
                    config = {"recursion_limit": self.s.max_graph_steps}
                    if self.saver is not None:
                        thread = await asyncio.to_thread(
                            self.store.thread, rid, principal, session["version"]
                        )
                        config["configurable"] = {"thread_id": thread}
                    if row.get("resume_count", 0):
                        if self.saver is None or self.provider.source != "mock":
                            raise Fault(
                                "RESUME_UNCERTAIN", "付费节点重放需要先核对在途请求；不自动重新计费。"
                            )
                        checkpoint = await self.graph.aget_state(config)
                        if (
                            not checkpoint.values
                            or checkpoint.values.get("workflow_version") != WORKFLOW_VERSION
                        ):
                            raise Fault("WORKFLOW_VERSION")
                        if checkpoint.next:
                            result = await self.graph.ainvoke(None, config, durability="sync")
                        elif checkpoint.values.get("done") and checkpoint.values.get("output"):
                            result = checkpoint.values
                        else:
                            raise Fault("INCOMPLETE_CHECKPOINT", "恢复点未完成，保留证据供核对。")
                    else:
                        result = await self.graph.ainvoke(
                            state, config, **({"durability": "sync"} if self.saver is not None else {})
                        )
                finally:
                    CURRENT_BUDGET.reset(budget_context)
                output = {
                    **result["output"],
                    "usage": budget.usage(),
                    "decisions": budget.decisions,
                    "model": self.s.model if self.provider.source == "model" else "offline-rules",
                    "reasoning_effort": self.s.thinking_effort if self.provider.source == "model" else None,
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
        except Exception as exc:
            import traceback

            frames = traceback.extract_tb(exc.__traceback__)
            await asyncio.to_thread(
                self.store.event,
                rid,
                "internal_error",
                {
                    "type": type(exc).__name__,
                    "function": frames[-1].name if frames else "unknown",
                    "line": frames[-1].lineno if frames else 0,
                    "key": exc.args[0]
                    if isinstance(exc, KeyError)
                    and exc.args
                    and exc.args[0] in {"output", "plan", "question", "version", "principal", "run_id"}
                    else None,
                },
            )
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
            if status == "succeeded":
                self.telemetry.business.labels(output["disposition"]).inc()
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

    async def resume(self, rid, principal):
        if self.saver is None or self.provider.source != "mock":
            raise Fault("RESUME_UNCERTAIN")
        row = await asyncio.to_thread(self.store.resume, rid, principal, self.s.request_seconds)
        if row is not None:
            self.principals[rid] = principal
            self.tasks[rid] = asyncio.create_task(self._run(row))

            def done(task):
                self.tasks.pop(rid, None)
                self.principals.pop(rid, None)

            self.tasks[rid].add_done_callback(done)
        return await asyncio.to_thread(self.store.get, rid, principal)

    async def close(self):
        self.closing = True
        if self.reaper:
            self.reaper.cancel()
            with suppress(asyncio.CancelledError):
                await self.reaper
        tasks = list(self.tasks.values())
        for rid, task in list(self.tasks.items()):
            principal = self.principals.get(rid)
            if principal is not None:
                await self.cancel(rid, principal)
            else:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.provider.close()
        await asyncio.to_thread(self.executor.close)
        await asyncio.to_thread(self.store.close)
        if self.checkpoint_pool is not None:
            await self.checkpoint_pool.close()
        self.telemetry.trace_provider.shutdown()
