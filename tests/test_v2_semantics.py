import asyncio
from datetime import datetime, timezone
import pytest
from insightflow.v2.contracts import QueryPlan
from insightflow.v2.semantics import explicit_windows, guard_question, reference_sql, SemanticSQLGuard
from insightflow.v2.mock import OfflineProvider
from insightflow.v2.errors import Fault
from insightflow.database.validator import SQLValidator
from insightflow.database.metadata import TableMetadata
from insightflow.v2.provider import RequestBudget

CLOCK = datetime(2026, 10, 1, tzinfo=timezone.utc)


def plan(question, previous=None, clock=CLOCK):
    from insightflow.v2.contracts import Decision

    return asyncio.run(
        OfflineProvider(clock).request(
            "plan", {"question": question, "previous": previous}, Decision, RequestBudget("x", 999999999)
        )
    )


@pytest.mark.parametrize(
    "question,start,end",
    [
        ("近30天订单数是多少？", "2026-09-01", "2026-10-01"),
        ("最近7天订单数", "2026-09-24", "2026-10-01"),
        ("过去1天订单数", "2026-09-30", "2026-10-01"),
        ("2026年9月订单数", "2026-09-01", "2026-10-01"),
        ("上月订单数", "2026-09-01", "2026-10-01"),
        ("2026-08-15至2026-09-12订单数", "2026-08-15", "2026-09-12"),
        ("2026年7月至9月订单数", "2026-07-01", "2026-10-01"),
    ],
)
def test_explicit_windows(question, start, end):
    w = explicit_windows(question, CLOCK)[0]
    assert w.start.date().isoformat() == start and w.end.date().isoformat() == end


@pytest.mark.parametrize(
    "clock,days,start",
    [
        ("2024-03-01", 1, "2024-02-29"),
        ("2024-03-01", 30, "2024-01-31"),
        ("2025-01-01", 1, "2024-12-31"),
        ("2026-01-15", 30, "2025-12-16"),
        ("2026-03-01", 1, "2026-02-28"),
        ("2028-03-01", 1, "2028-02-29"),
    ],
)
def test_clock_boundaries(clock, days, start):
    w = explicit_windows(f"近{days}天订单数", datetime.fromisoformat(clock).replace(tzinfo=timezone.utc))[0]
    assert w.start.date().isoformat() == start


@pytest.mark.parametrize("region", ["华东", "华南", "华北", "西部"])
@pytest.mark.parametrize("negation", ["排除", "不含", "不包括", "不要"])
def test_exclusion_not_inclusion(region, negation):
    q = f"2026年9月{negation}{region}地区的订单数是多少？"
    p = plan(q).plan
    guard_question(q, p, {}, CLOCK)
    assert p.exclude_regions == [region] and not p.include_regions
    assert "NOT IN" in reference_sql(p)
    wrong = p.model_copy(update={"include_regions": [region], "exclude_regions": []})
    with pytest.raises(Fault, match="地区"):
        guard_question(q, wrong, {}, CLOCK)


def test_recent_and_yoy_regressions():
    p = plan("近30天订单数是多少？").plan
    with pytest.raises(Fault, match="日期"):
        guard_question("近30天订单数是多少？", p.model_copy(update={"windows": []}), {}, CLOCK)
    q = "2026年9月订单数同比增长多少？"
    p = plan(q).plan
    assert p.comparison == "yoy" and p.comparison_window.start.year == 2025
    with pytest.raises(Fault, match="覆盖"):
        guard_question(q, p, {}, CLOCK)
    with pytest.raises(Fault, match="对比"):
        guard_question(q, p.model_copy(update={"comparison": "none", "comparison_window": None}), {}, CLOCK)


def test_inheritance_override_missing_and_conflict():
    a = plan("2026年9月华东订单数").plan
    b = plan("那华南地区呢？", a.model_dump(mode="json")).plan
    assert b.windows == a.windows and b.include_regions == ["华南"]
    guard_question("那华南地区呢？", b, a.model_dump(mode="json"), CLOCK)
    with pytest.raises(Fault):
        guard_question(
            "那华南地区呢？", b.model_copy(update={"windows": []}), a.model_dump(mode="json"), CLOCK
        )
    assert plan("那第二个呢？").disposition == "clarify"
    with pytest.raises(ValueError):
        QueryPlan(
            metric="order_count", aggregation="count", include_regions=["华东"], exclude_regions=["华东"]
        )


@pytest.fixture
def validator():
    specs = {
        "orders": {
            "id": "integer",
            "customer_id": "integer",
            "ordered_at": "timestamp with time zone",
            "status": "text",
        },
        "customers": {
            "id": "integer",
            "name": "text",
            "region": "text",
            "created_at": "timestamp with time zone",
        },
        "products": {"id": "integer", "name": "text", "category": "text", "price": "numeric"},
        "order_items": {
            "id": "integer",
            "order_id": "integer",
            "product_id": "integer",
            "quantity": "integer",
            "unit_price": "numeric",
        },
        "refunds": {
            "id": "integer",
            "order_id": "integer",
            "refund_amount": "numeric",
            "status": "text",
            "refunded_at": "timestamp with time zone",
        },
    }
    return SQLValidator(
        {n: TableMetadata(table_name=n, columns=c, foreign_keys=[]) for n, c in specs.items()}
    )


@pytest.mark.parametrize(
    "question",
    [
        "2026年9月订单数",
        "2026年9月排除华东订单数",
        "2026年9月各地区订单数",
        "2026年9月销售额",
        "2026年9月GMV",
        "2026年9月退款金额",
        "2026年9月退款率",
        "2026年9月退款金额率",
        "2026年9月客单价",
        "商品数",
        "客户数",
        "平均标价",
        "2026年7月和9月订单数",
        "2026年9月按月订单数",
        "2026年9月各地区订单数前2",
    ],
)
def test_sql_contract_roundtrip(question, validator):
    p = plan(question).plan
    guard_question(question, p, {}, CLOCK)
    sql = reference_sql(p)
    assert SemanticSQLGuard(validator).validate(sql, p)


def test_equivalent_time_format_and_count_pk(validator):
    p = plan("2026年9月订单数").plan
    sql = "select count(o.id) as value from business.orders o where o.ordered_at >= '2026-09-01' and o.ordered_at < '2026-10-01'"
    assert SemanticSQLGuard(validator).validate(sql, p)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.replace("NOT IN", "IN"),
        lambda s: s.replace("2026-09-01", "2026-08-01"),
        lambda s: s.replace("COUNT(*)", "COUNT(DISTINCT o.customer_id)"),
        lambda s: s.replace("c.region NOT IN ('华东')", "1 = 1"),
    ],
)
def test_safe_but_wrong_sql_rejected(validator, mutate):
    p = plan("2026年9月排除华东订单数").plan
    with pytest.raises(Fault):
        SemanticSQLGuard(validator).validate(mutate(reference_sql(p)), p)


@pytest.mark.parametrize(
    "q",
    [
        "2026年9月利润是多少",
        "2026年9月美元销售额",
        "为什么销售额增长",
        "季度订单数",
        "近0天订单数",
        "近999天订单数",
        "2026-09-01订单数",
    ],
)
def test_unsupported_clarifies(q):
    d = plan(q)
    if d.disposition == "query":
        with pytest.raises(Fault):
            guard_question(q, d.plan, {}, CLOCK)
    else:
        assert d.disposition == "clarify"


def test_wrong_metric_plan_rejected_even_if_its_sql_is_safe():
    wrong = plan("2026年9月已支付订单数").plan
    with pytest.raises(Fault, match="指标"):
        guard_question("2026年9月订单数是多少？", wrong, {}, CLOCK)
