"""One bounded LangGraph agent. V1 graph remains intact for frozen regression."""

import hashlib
import json
import re
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from insightflow.database.errors import AgentError
from insightflow.retrieval.glossary import METRICS
from insightflow.v2.contracts import Decision, Action, Answer
from insightflow.v2.errors import Fault
from insightflow.v2.semantics import guard_question, COVERAGE_START, COVERAGE_END

SQL_CONVENTIONS = """Use PostgreSQL canonical supported contract: physical tables business.orders AS o, customers AS c, products AS p.
Order counts COUNT(*) AS value; customer/product counts COUNT(*) AS value. Product avg/min/max use p.price.
Date predicates o.ordered_at >= CAST('YYYY-MM-DDTHH:MM:SSZ' AS TIMESTAMPTZ) AND o.ordered_at < CAST(... AS TIMESTAMPTZ), wrapped in parentheses; multiple windows OR.
Order/customer join o.customer_id = c.id. Regions c.region IN (...) or NOT IN (...), alphabetically sorted values. All explicit filters AND, time then status then include then exclude.
Status for paid metrics o.status = 'paid'; GMV o.status <> 'cancelled'; pending/cancelled counts their exact status.
For money use LEFT JOIN (SELECT order_id, SUM(quantity * unit_price) AS revenue FROM business.order_items GROUP BY order_id) AS s ON o.id = s.order_id.
For refunds use LEFT JOIN (SELECT order_id, SUM(refund_amount) AS refunded FROM business.refunds WHERE status = 'succeeded' GROUP BY order_id) AS r ON o.id = r.order_id.
Sales joins precede refunds. Never join raw items and raw refunds together. Sum money COALESCE(SUM(s.revenue), 0); refund COALESCE(SUM(r.refunded), 0).
Refund order ratio CAST(COUNT(r.order_id) AS NUMERIC) / NULLIF(COUNT(*), 0); refund amount ratio COALESCE(SUM(r.refunded), 0) / NULLIF(SUM(s.revenue), 0); AOV SUM(s.revenue) / NULLIF(COUNT(*), 0).
For dimensions SELECT <dimension> AS dimension, <metric> AS value GROUP BY <dimension> ORDER BY value DESC/ASC, dimension ASC. Month dimension DATE_TRUNC('month', o.ordered_at); region c.region; category p.category; product p.name. Top uses LIMIT N.
No grouping means no ORDER BY/LIMIT. SQL repairs can only fix recoverable semantic/field/syntax errors. Safety/permission rejection is terminal.
Comparisons: execute current and comparison SQL separately with period argument then compare tool. Do not silently omit comparisons.
"""


class AgentState(TypedDict, total=False):
    question: str
    previous: dict
    run_id: str
    source: str
    budget: object
    plan: object
    selected: dict
    decision: object
    tool_results: list
    evidence_by_period: dict
    evidence: dict
    evidence_id: str
    compared: bool
    repairs: int
    action: object
    output: dict
    done: bool
    error: dict


def verify_answer(answer, evidence, eid):
    if re.search(r"\d|导致|造成|证明|因为|由于|翻倍|翻番", answer.explanation):
        raise Fault("ANSWER_GROUNDING", "自然语言包含未经绑定的数字或因果陈述。")
    for citation in answer.citations:
        if citation.evidence_id != eid:
            raise Fault("ANSWER_GROUNDING", "证据引用不属于当前运行。")
        try:
            value = evidence["rows"][citation.row][citation.column]
        except (IndexError, KeyError):
            raise Fault("ANSWER_GROUNDING", "引用越界。") from None
        if (
            value is None
            and citation.value is not None
            or value is not None
            and str(value) != str(citation.value)
        ):
            raise Fault("ANSWER_GROUNDING", "引用数字与结构化证据不一致。")
    # Untrusted model limitations are also checked; server supplies authoritative boundaries.
    if any(re.search(r"\d|导致|造成|证明|因为|由于", x) for x in answer.limitations):
        raise Fault("ANSWER_GROUNDING", "模型限制说明含未经绑定的断言。")
    return True


def build_graph(provider, registry, settings, store, telemetry):
    async def plan(s):
        await_event(s, "understanding")
        previous = s["previous"] if settings.context_enabled else {}
        d = await provider.request(
            "plan",
            {
                "question": s["question"],
                "previous": previous,
                "reference_time": settings.reference_time.isoformat(),
                "coverage": [COVERAGE_START.isoformat(), COVERAGE_END.isoformat()],
                "trusted_metrics": METRICS,
                "rules": "Interpret all modifiers; uncertainty -> clarify. Relative N days = N complete UTC days before reference day; do not substitute data max time. Explicit conditions override, omitted conditions inherit. No unseen data counted as zero.",
            },
            Decision,
            s["budget"],
        )
        if d.disposition != "query":
            return {
                "done": True,
                "decision": d,
                "output": {"disposition": d.disposition, "answer": d.message, "evidence": {}, "sql": []},
            }
        try:
            p = guard_question(s["question"], d.plan, previous, settings.reference_time)
        except Fault as exc:
            if exc.code == "SAFETY_DENIED":
                disposition = "reject"
            elif exc.code == "CLARIFICATION":
                disposition = "clarify"
            else:
                raise
            return {
                "done": True,
                "decision": d,
                "output": {"disposition": disposition, "answer": exc.message, "evidence": {}, "sql": []},
            }
        return {"plan": p, "decision": d}

    def await_event(s, stage, payload=None):
        # event() is synchronous but each write is short; wrapper nodes offload when appropriate below.
        store.event(s["run_id"], stage, payload)

    async def retrieve(s):
        import asyncio

        with telemetry.stage("retrieval", s["run_id"]):
            selected = await asyncio.to_thread(
                registry.retriever.select, s["question"], s["plan"], settings.retrieval_mode
            )
        await asyncio.to_thread(
            store.event,
            s["run_id"],
            "retrieval",
            {"schema_version": selected["schema_version"], "table_count": len(selected["tables"])},
        )
        return {"selected": selected}

    async def action(s):
        if len(s["tool_results"]) >= settings.max_tool_calls:
            raise Fault("TOOL_BUDGET", "工具调用预算已耗尽。")
        feedback = (
            s["tool_results"]
            if settings.feedback_enabled
            else [x for x in s["tool_results"] if x["status"] == "ok"]
        )
        a = await provider.request(
            "action",
            {
                "question": s["question"],
                "plan": s["plan"].model_dump(mode="json"),
                "authorized_schema": s["selected"],
                "sql_conventions": SQL_CONVENTIONS,
                "tool_contracts": registry.contracts(),
                "tool_results": [
                    {
                        **x,
                        "value": (
                            {
                                k: v
                                for k, v in x["value"].items()
                                if k
                                in (
                                    "period",
                                    "error",
                                    "sql",
                                    "columns",
                                    "rows",
                                    "evidence_id",
                                    "metric",
                                    "definition",
                                )
                            }
                            if x["name"] not in ("schema",)
                            else {"schema_version": x["value"].get("schema_version")}
                        ),
                    }
                    for x in feedback
                ],
                "evidence_id": s.get("evidence_id"),
                "used_call_ids": [x["call_id"] for x in s["tool_results"]],
                "next_call_id": "step_" + str(len(s["tool_results"]) + 1),
                "instruction": "Use next_call_id as a NEW call_id. If schema not successful choose schema. Else if metric not successful choose metric. Else execute_sql directly (it validates internally), then comparison if required. Never repeat successful tools. Do not invent native tool_call messages.",
            },
            Action,
            s["budget"],
        )
        return {"action": a}

    async def tool(s):
        import asyncio

        a = s["action"]
        results = list(s["tool_results"])
        if any(x["call_id"] == a.call_id for x in results):
            raise Fault("TOOL_LOOP", "工具调用ID重复。")
        digest = hashlib.sha256(
            json.dumps(a.arguments, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        if (
            any(x["name"] == a.name and x["input_digest"] == digest and x["status"] == "ok" for x in results)
            or sum(x["name"] == a.name and x["input_digest"] == digest for x in results) >= 2
        ):
            raise Fault("TOOL_LOOP", "重复相同工具请求，没有新证据。")
        await asyncio.to_thread(
            store.event,
            s["run_id"],
            "tool_started",
            {"call_id": a.call_id, "name": a.name, "source": s["source"], "input_digest": digest},
        )
        changes = {}
        try:
            with telemetry.stage("tool", s["run_id"]):
                value = await registry.execute(a, s)
            for key in ("evidence_by_period", "evidence_id", "evidence", "compared"):
                if key in s:
                    changes[key] = s[key]
        except (Fault, AgentError) as exc:
            code = exc.code if isinstance(exc, Fault) else exc.kind.value
            recoverable = exc.retryable and code not in (
                "SQL_VALIDATION_ERROR",
                "SCHEMA_DENIED",
                "TOOL_DENIED",
            )
            value = {
                "call_id": a.call_id,
                "name": a.name,
                "source": s["source"],
                "status": "error",
                "input_digest": digest,
                "result_ref": "error-" + a.call_id,
                "value": {
                    "error": {
                        "code": code,
                        "message": str(exc)[:250] if isinstance(exc, Fault) else exc.message,
                        "recoverable": recoverable,
                    }
                },
            }
            results.append(value)
            await asyncio.to_thread(
                store.event,
                s["run_id"],
                "tool_finished",
                {
                    "call_id": a.call_id,
                    "name": a.name,
                    "status": "error",
                    "code": code,
                    "result_ref": value["result_ref"],
                },
            )
            if not recoverable or s["repairs"] >= settings.max_sql_repairs or not settings.feedback_enabled:
                raise Fault(code, value["value"]["error"]["message"])
            telemetry.retries.labels("tool_feedback").inc()
            return {"tool_results": results, "repairs": s["repairs"] + 1}
        results.append(value)
        await asyncio.to_thread(
            store.event,
            s["run_id"],
            "tool_finished",
            {"call_id": a.call_id, "name": a.name, "status": "ok", "result_ref": value["result_ref"]},
        )
        return {"tool_results": results, **changes}

    async def answer(s):
        import asyncio

        await asyncio.to_thread(store.event, s["run_id"], "answering")
        evidence = s["evidence"]
        eid = s["evidence_id"]
        source = "model" if provider.source == "model" else "mock"
        generated = None
        if evidence["rows"]:
            try:
                generated = await provider.request(
                    "answer",
                    {
                        "question": s["question"],
                        "plan": s["plan"].model_dump(mode="json"),
                        "evidence": evidence,
                        "evidence_id": eid,
                        "rules": "Explain without any digits or causal assertions. Use citations for exact values; no private reasoning.",
                    },
                    Answer,
                    s["budget"],
                )
                verify_answer(generated, evidence, eid)
            except Fault as exc:
                if exc.code not in ("ANSWER_GROUNDING", "MODEL_INVALID", "MODEL_TRUNCATED"):
                    raise
                source = "deterministic_fallback"
        else:
            source = "deterministic_empty"
        output = {
            "disposition": "answer",
            "answer": generated.explanation
            if generated and source != "deterministic_fallback"
            else "以下为已验证查询证据；空结果或NULL不当作零。",
            "answer_source": source,
            "citations": [x.model_dump() for x in generated.citations]
            if generated and source != "deterministic_fallback"
            else [],
            "metric": s["plan"].metric,
            "metric_definition": METRICS[s["plan"].metric],
            "time_windows": [x.model_dump(mode="json") for x in s["plan"].windows],
            "comparison_window": s["plan"].comparison_window.model_dump(mode="json")
            if s["plan"].comparison_window
            else None,
            "evidence_id": eid,
            "evidence": evidence,
            "sql": [
                x["value"]["sql"]
                for x in s["tool_results"]
                if x["name"] == "execute_sql" and x["status"] == "ok"
            ],
            "sql_by_period": {k: v["sql"] for k, v in s["evidence_by_period"].items()},
            "limitations": [
                "合成数据；CNY/UTC；口径2026-10-v1；不推断因果。",
                "会话隔离不等于业务行级多租户隔离。",
                "SQL语义检查仅支持文档中的保守契约，不证明任意SQL等价。",
            ],
            "tool_records": [{k: v for k, v in x.items() if k != "value"} for x in s["tool_results"]],
            "repairs": s["repairs"],
            "schema_version": s["selected"]["schema_version"],
        }
        return {"output": output, "done": True}

    g = StateGraph(AgentState)
    for name, node in [
        ("plan", plan),
        ("retrieve", retrieve),
        ("action", action),
        ("tool", tool),
        ("answer", answer),
    ]:
        g.add_node(name, node)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", lambda s: END if s.get("done") else "retrieve")
    g.add_edge("retrieve", "action")
    g.add_edge("action", "tool")

    def after_tool(s):
        if s.get("evidence") is not None and (s["plan"].comparison == "none" or s.get("compared")):
            return "answer"
        return "action"

    g.add_conditional_edges("tool", after_tool)
    g.add_edge("answer", END)
    return g.compile()
