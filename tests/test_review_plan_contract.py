import asyncio
import json
import time
from datetime import datetime, timezone
import httpx
import pytest
from insightflow.v2.config import V2Settings
from insightflow.v2.contracts import QueryPlan, Window
from insightflow.v2.checkpoints import CURRENT_BUDGET, WORKFLOW_VERSION
from insightflow.v2.graph import build_graph
from insightflow.v2.provider import AsyncDeepSeek, RequestBudget
from insightflow.v2.semantics import guard_question
from insightflow.v2.telemetry import Telemetry
from insightflow.v2.errors import Fault

CLOCK = datetime(2026, 10, 1, tzinfo=timezone.utc)
SEPTEMBER = Window(start="2026-09-01T00:00:00Z", end="2026-10-01T00:00:00Z")


class Ledger:
    def reserve(self, *args):
        return "synthetic-attempt"

    def settle(self, *args):
        pass

    def event(self, *args):
        pass


@pytest.mark.parametrize(
    "question,updates",
    [
        ("2025年9月订单数", {"windows": [SEPTEMBER]}),
        ("2100年9月订单数", {"windows": [SEPTEMBER]}),
        (
            "2026年9月退款金额率",
            {"metric": "refunded_order_rate", "aggregation": "ratio", "windows": [SEPTEMBER]},
        ),
        ("2026年7月和9月订单数", {"windows": [SEPTEMBER]}),
        ("订单数", {"windows": [SEPTEMBER]}),
        ("订单数", {"include_regions": ["华东"]}),
    ],
)
def test_real_adapter_plan_protocol_rejects_semantically_wrong_plan_before_tools(question, updates):
    async def run():
        plan = (
            QueryPlan(metric="order_count", aggregation="count", **updates)
            if "metric" not in updates
            else QueryPlan(**updates)
        )
        calls = []

        async def response(request):
            payload = json.loads(request.content)
            context = json.loads(payload["messages"][-1]["content"])
            assert "trusted_metrics" in context and context["reference_time"].startswith("2026-10-01")
            assert payload["reasoning_effort"] == "max"
            calls.append(context)
            return httpx.Response(
                200,
                json={
                    "model": "deepseek-flash",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {"disposition": "query", "plan": plan.model_dump(mode="json")}
                                )
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
                },
            )

        class NoTools:
            @property
            def retriever(self):
                raise AssertionError("Unverified plan reached tools")

        settings = V2Settings(
            runtime_url="unused",
            reader_url="unused",
            auth_tokens={"synthetic-review-long-token-only": "review"},
            mode="deepseek",
            live_enabled=True,
            api_key="synthetic",
        )
        client = httpx.AsyncClient(transport=httpx.MockTransport(response))
        telemetry = Telemetry()
        provider = AsyncDeepSeek(settings, Ledger(), telemetry, client)
        token = CURRENT_BUDGET.set(RequestBudget("review", time.monotonic() + 10))
        try:
            graph = build_graph(provider, NoTools(), settings, Ledger(), telemetry)
            with pytest.raises(Fault) as exc:
                await graph.ainvoke(
                    {
                        "question": question,
                        "previous": {},
                        "run_id": "review",
                        "source": "model",
                        "workflow_version": WORKFLOW_VERSION,
                        "tool_results": [],
                        "repairs": 0,
                    }
                )
            assert exc.value.code == "SEMANTIC_MISMATCH" and len(calls) == 1
        finally:
            CURRENT_BUDGET.reset(token)
            await provider.close()
            telemetry.trace_provider.shutdown()

    asyncio.run(run())


def test_explicit_correction_and_reset_override_old_session_constraints():
    previous = QueryPlan(
        metric="order_count", aggregation="count", windows=[SEPTEMBER], include_regions=["华东"]
    ).model_dump(mode="json")
    corrected = QueryPlan(
        metric="order_count", aggregation="count", windows=[SEPTEMBER], include_regions=["华南"]
    )
    assert guard_question("那华南地区呢", corrected, previous, CLOCK).include_regions == ["华南"]
    with pytest.raises(Fault):
        guard_question("全国订单数", QueryPlan.model_validate(previous), previous, CLOCK)
    national = QueryPlan(metric="order_count", aggregation="count", windows=[SEPTEMBER])
    assert guard_question("全国订单数", national, previous, CLOCK).include_regions == []
    master = QueryPlan(metric="product_count", aggregation="count")
    assert guard_question("商品数", master, previous, CLOCK).windows == []


@pytest.mark.parametrize("question", ["2025年订单数", "2026年订单数", "2100年订单数"])
def test_year_only_scope_requires_clarification_instead_of_an_unbounded_query(question):
    with pytest.raises(Fault) as exc:
        guard_question(question, QueryPlan(metric="order_count", aggregation="count"), {}, CLOCK)
    assert exc.value.code == "CLARIFICATION"


def test_old_graph_state_is_rejected_before_provider_or_tools():
    async def run():
        settings = V2Settings(
            runtime_url="unused",
            reader_url="unused",
            auth_tokens={"synthetic-review-version-token": "review"},
        )
        telemetry = Telemetry()
        try:
            graph = build_graph(object(), object(), settings, object(), telemetry)
            with pytest.raises(Fault) as exc:
                await graph.ainvoke({"workflow_version": "pilot-graph-v1", "run_id": "old-review"})
            assert exc.value.code == "WORKFLOW_VERSION"
        finally:
            telemetry.trace_provider.shutdown()

    asyncio.run(run())
