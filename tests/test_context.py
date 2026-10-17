import json
import pytest
from pydantic import SecretStr
from insightflow.config import Settings
from insightflow.agent.service import AgentService
from insightflow.context.manager import ContextManager
from insightflow.context.session import SessionStore
from insightflow.database.errors import AgentError
from insightflow.llm.base import Plan


@pytest.mark.integration
def test_multiturn_inheritance_isolation_override(database_urls):
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    try:
        first = svc.run("2026年9月退款率是多少？", "alpha")
        assert first["error"] is None
        follow = svc.run("那华东地区呢？", "alpha")
        assert follow["plan"]["month"] == "2026-09"
        assert follow["plan"]["metric"] == "refunded_order_rate"
        assert follow["plan"]["region"] == "华东"
        other = svc.run("那华东地区呢？", "beta")
        assert other["error"]["kind"] == "CLARIFICATION_REQUIRED"
        override = svc.run("改成2026年8月呢？", "alpha")
        assert override["plan"]["month"] == "2026-08" and override["plan"]["region"] == "华东"
        assert override["plan"]["currency"] == "CNY"
        assert svc.run("那全部地区呢？", "alpha")["plan"]["region"] is None
    finally:
        svc.close()


def test_context_budget_preserves_constraints():
    plan = Plan(metric="refunded_order_rate", month="2026-09", region="华东")
    retrieval = {
        "retrieved_metrics": {"refunded_order_rate": "有退款支付订单数/已支付订单数"},
        "schemas": [{"table_name": "orders", "columns": {"id": "integer"}}],
    }
    context = ContextManager(Settings(max_context_tokens=500))
    built = context.build(
        "那华东呢？",
        plan,
        retrieval,
        [{"question": "old", "tool_output": "x" * 12000}, {"question": "recent", "answer": "y" * 12000}],
    )
    assert built["estimated_tokens"] <= 500 and built["removed_history_items"] >= 2
    data = json.loads(built["text"])
    assert data["authoritative_constraints"] == plan.model_dump()
    assert built["token_measurement"].startswith("estimated")
    with pytest.raises(AgentError):
        ContextManager(Settings(max_context_tokens=100)).build("长" * 2000, plan, retrieval, [])


def test_inmemory_boundaries():
    store = SessionStore(max_turns=1, capacity=1, ttl=100)
    session = store.get("one")
    store.record(
        session,
        "q",
        {
            "error": None,
            "query_result": {"rows": [[1]]},
            "plan": {"metric": "order_count"},
            "final_answer": {"answer": "1"},
        },
    )
    assert SessionStore().get("one").constraints == {}  # restart loses memory
    with pytest.raises(AgentError):
        store.get("two")


@pytest.mark.parametrize(
    "question,month",
    [
        ("9月退款率是多少？", "2026-09"),
        ("上月退款率是多少？", "2026-09"),
        ("本月退款率是多少？", "2026-10"),
        ("今年9月退款率是多少？", "2026-09"),
    ],
)
def test_fixed_reference_relative_month(question, month):
    from insightflow.llm.mock import parse_question

    assert parse_question(question, {}).month == month


@pytest.mark.parametrize(
    "question",
    [
        "2025年9月退款率是多少？",
        "2026年9月1日退款率是多少？",
        "第一季度销售收入是多少？",
        "美元销售收入是多少？",
    ],
)
def test_unsupported_time_currency_requests_clarification(question):
    from insightflow.llm.mock import parse_question

    with pytest.raises(AgentError) as exc:
        parse_question(question, {})
    assert exc.value.kind.value == "CLARIFICATION_REQUIRED"


@pytest.mark.parametrize(
    "question", ["2026年8月到9月订单数是多少？", "比较2026年8月和9月订单数", "2026年8-9月订单数是多少？"]
)
def test_multiple_months_never_silently_narrow_to_first(question):
    from insightflow.llm.mock import parse_question

    with pytest.raises(AgentError) as exc:
        parse_question(question, {})
    assert exc.value.kind.value == "CLARIFICATION_REQUIRED"
