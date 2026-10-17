from pathlib import Path
import json
import pytest
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.llm.mock import MockLLMProvider, parse_question
from insightflow.llm.base import Generation, Plan
from insightflow.database.metadata import read_catalog, TableMetadata
from insightflow.retrieval.retriever import SchemaRetriever


@pytest.mark.integration
def test_four_modes_real_queries_and_common_security(database_urls):
    from insightflow.evaluation.ablation import experiment

    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evaldata/questions.json").read_text())
    labels = json.loads((root / "evaldata/retrieval_labels.json").read_text())
    records, summary = experiment(database_urls[0], cases, labels)
    assert len(records) == 120
    assert summary["full"]["success_rate"] == summary["context_only"]["success_rate"] == 1
    assert summary["baseline"]["success_rate"] == summary["retrieval_only"]["success_rate"] == 25 / 30
    # Mock ignores Schema text: do not manufacture a retrieval quality improvement.
    assert summary["baseline"]["sql_result_accuracy"] == summary["retrieval_only"]["sql_result_accuracy"]
    assert summary["context_only"]["sql_result_accuracy"] == summary["full"]["sql_result_accuracy"]
    assert summary["full"]["recall_at_k"] == 1
    assert any(
        r["failure_category"] == "Context Resolution Error" for r in records if not r["scenario_success"]
    )
    for mode in summary:
        svc = AgentService(Settings(database_url=SecretStr(database_urls[0]), experiment_mode=mode))
        try:
            from insightflow.database.errors import AgentError

            with pytest.raises(AgentError):
                svc.executor.execute("SELECT * FROM pg_catalog.pg_authid")
            assert set(svc.executor.validator.catalog) == {
                "customers",
                "products",
                "orders",
                "order_items",
                "refunds",
            }
        finally:
            svc.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    "metric,group,region,expected",
    [
        ("customer_count", None, None, {"customers"}),
        ("paid_revenue", None, None, {"orders", "order_items"}),
        ("paid_revenue", "category", None, {"orders", "order_items", "products"}),
        ("refunded_order_rate", None, "华东", {"orders", "refunds", "customers"}),
    ],
)
def test_independent_table_selection_and_fk(database_urls, metric, group, region, expected):
    catalog = read_catalog(database_urls[0])
    result = SchemaRetriever(catalog).retrieve("查询", Plan(metric=metric, group=group, region=region))
    assert set(result["retrieved_tables"]) == expected
    assert all("." in c for c in result["retrieved_columns"])
    assert any(fk["target_table"] == "products" for fk in catalog["order_items"].foreign_keys)


@pytest.mark.integration
def test_unauthorized_catalog_noise_never_retrieved(database_urls):
    catalog = read_catalog(database_urls[0])
    catalog["secret_payroll"] = TableMetadata(
        table_name="secret_payroll", columns={"salary": "numeric"}, foreign_keys=[]
    )
    result = SchemaRetriever(catalog).retrieve("secret_payroll salary 员工工资", Plan(metric="order_count"))
    assert result["retrieved_tables"] == ["orders"]
    assert "salary" not in str(result) and "secret_payroll" not in str(result)
    assert (
        "nonexistent"
        not in SchemaRetriever(catalog).retrieve("nonexistent", Plan(metric="product_count"))[
            "retrieved_tables"
        ]
    )


@pytest.mark.parametrize(
    "question,metric",
    [
        ("退货率是多少？", "refunded_order_rate"),
        ("营收是多少？", "paid_revenue"),
        ("2026 年 9 月订单数是多少？", "order_count"),
    ],
)
def test_business_synonyms(question, metric):
    assert parse_question(question, {}).metric == metric


@pytest.mark.integration
def test_context_cases_overwrite_switch_growth_and_ambiguity(database_urls):
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    try:
        svc.run("2026 年 9 月订单数是多少？", "b")
        changed = svc.run("改成 8 月。", "b")
        assert changed["plan"]["month"] == "2026-08" and changed["plan"]["metric"] == "order_count"
        svc.run("华东地区退款订单率是多少？", "c")
        switch = svc.run("那退款金额率呢？", "c")
        assert switch["plan"]["metric"] == "refund_amount_rate" and switch["plan"]["region"] == "华东"
        for month in range(1, 10):
            result = svc.run(f"2026年{month}月订单数是多少？", "growth")
            assert result["error"] is None
        last = svc.run("那华东地区呢？", "growth")
        assert last["plan"]["month"] == "2026-09"
        assert len(svc.sessions.get("growth").history) <= 4
        assert last["context_budget"]["estimated_tokens"] <= svc.settings.max_context_tokens
        assert svc.run("那第二个呢？", "growth")["error"]["kind"] == "CLARIFICATION_REQUIRED"
    finally:
        svc.close()


@pytest.mark.integration
def test_failed_history_not_authoritative_and_no_ground_truth_in_prompt(database_urls):
    class Switch(MockLLMProvider):
        broken = False
        captured = []

        def generate(self, plan, context, feedback):
            self.captured.append(context)
            return (
                Generation(sql="SELECT missing FROM business.orders")
                if self.broken
                else super().generate(plan, context, feedback)
            )

    provider = Switch()
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])), provider)
    try:
        svc.run("2026年9月华东地区已支付订单数是多少？", "safe")
        before = dict(svc.sessions.get("safe").constraints)
        provider.broken = True
        failed = svc.run("2026年8月订单数是多少？", "safe")
        assert failed["error"] is not None and svc.sessions.get("safe").constraints == before
        provider.broken = False
        resumed = svc.run("那华南地区呢？", "safe")
        assert resumed["plan"]["month"] == "2026-09" and resumed["plan"]["metric"] == "paid_order_count"
        assert all(
            "expected_result" not in ctx and "reference_sql" not in ctx and "case_id" not in ctx
            for ctx in provider.captured
        )
    finally:
        svc.close()
