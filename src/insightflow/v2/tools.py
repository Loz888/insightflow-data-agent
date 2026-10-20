from insightflow.v2.checkpoints import CURRENT_BUDGET
import asyncio
import hashlib
import json
from decimal import Decimal
from uuid import uuid4
from pydantic import ValidationError
from insightflow.agent.cancellation import Cancellation
from insightflow.database.errors import AgentError
from insightflow.v2.definitions import METRICS
from insightflow.v2.contracts import SchemaArgs, MetricArgs, SQLArgs, CompareArgs, ToolResult
from insightflow.v2.errors import Fault
from insightflow.v2.semantics import SemanticSQLGuard


class Registry:
    arguments = {
        "schema": SchemaArgs,
        "metric": MetricArgs,
        "validate_sql": SQLArgs,
        "execute_sql": SQLArgs,
        "compare": CompareArgs,
    }

    def __init__(self, retriever, executor, settings, telemetry):
        self.retriever = retriever
        self.executor = executor
        self.s = settings
        self.telemetry = telemetry
        self.guard = SemanticSQLGuard(executor.validator)
        self.db_gate = asyncio.Semaphore(settings.db_concurrency)

    def contracts(self):
        return {n: m.model_json_schema() for n, m in self.arguments.items()}

    async def execute(self, action, state):
        if action.name not in self.arguments:
            raise Fault("TOOL_DENIED", "未注册工具。")
        try:
            args = self.arguments[action.name].model_validate(action.arguments)
        except ValidationError:
            raise Fault("TOOL_ARGUMENT", "工具参数不符合契约。", True) from None
        name = action.name
        plan = state["plan"]
        successful = {x["name"] for x in state["tool_results"] if x["status"] == "ok"}
        if name == "schema":
            value = await asyncio.to_thread(self.retriever.select, args.query, plan, self.s.retrieval_mode)
        elif name == "metric":
            if args.metric != plan.metric:
                raise Fault("TOOL_ARGUMENT", "工具指标与计划不一致。", True)
            value = {
                "metric": plan.metric,
                "definition": METRICS[plan.metric],
                "version": plan.metric_version,
            }
        elif name in ("validate_sql", "execute_sql"):
            if not {"schema", "metric"} <= successful:
                raise Fault("TOOL_ORDER", "执行前必须查询授权Schema和指标口径。", True)
            if state.get("selected", {}).get("schema_version") != self.retriever.version:
                raise Fault("SCHEMA_CHANGED", "Schema已变化，请重新开始请求。")
            from insightflow.database.validator import SQLValidator

            current_validator = SQLValidator(self.retriever.tables)
            self.guard = SemanticSQLGuard(current_validator)
            self.executor.validator = current_validator
            validated = self.guard.validate(args.sql, plan, args.period)
            if name == "validate_sql":
                value = {"valid": True, "tables": validated.tables, "period": args.period}
            else:
                token = Cancellation()
                async with asyncio.timeout(min(self.s.queue_seconds, CURRENT_BUDGET.get().remaining())):
                    with self.telemetry.stage("db_queue", state["run_id"]):
                        await self.db_gate.acquire()
                try:
                    with self.telemetry.stage("sql", state["run_id"]):
                        worker = asyncio.create_task(
                            asyncio.to_thread(self.executor.execute, args.sql, token)
                        )
                        try:
                            result = await asyncio.shield(worker)
                        except asyncio.CancelledError:
                            token.cancel()
                            try:
                                await asyncio.shield(worker)
                            except (AgentError, asyncio.CancelledError):
                                pass
                            raise
                    evidence_id = str(uuid4())
                    value = {**result, "evidence_id": evidence_id, "sql": args.sql, "period": args.period}
                    state["evidence_by_period"][args.period] = value
                    state["evidence_id"] = evidence_id
                    state["evidence"] = result
                finally:
                    self.db_gate.release()
        else:
            cur = state["evidence_by_period"].get("current")
            prev = state["evidence_by_period"].get("comparison")
            if not cur or not prev or args.evidence_id != state["evidence_id"]:
                raise Fault("TOOL_ARGUMENT", "对比必须引用本运行中两个已验证区间的证据。", True)
            if (
                cur["columns"] != ["value"]
                or prev["columns"] != ["value"]
                or len(cur["rows"]) != 1
                or len(prev["rows"]) != 1
            ):
                raise Fault("TOOL_ARGUMENT", "对比仅支持单指标标量。")
            a, b = cur["rows"][0][0], prev["rows"][0][0]
            change = (
                None
                if a is None or b is None or Decimal(str(b)) == 0
                else str((Decimal(str(a)) - Decimal(str(b))) / Decimal(str(b)))
            )
            evidence_id = str(uuid4())
            value = {
                "columns": ["current", "previous", "change_rate"],
                "rows": [[a, b, change]],
                "row_count": 1,
                "evidence_id": evidence_id,
                "source_refs": [cur["evidence_id"], prev["evidence_id"]],
            }
            state["evidence_id"] = evidence_id
            state["evidence"] = {k: value[k] for k in ("columns", "rows", "row_count")}
            state["compared"] = True
        digest = hashlib.sha256(
            json.dumps(action.arguments, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return ToolResult(
            call_id=action.call_id,
            name=name,
            source=state["source"],
            status="ok",
            input_digest=digest,
            result_ref=value.get("evidence_id", str(uuid4())),
            value=value,
        ).model_dump()
