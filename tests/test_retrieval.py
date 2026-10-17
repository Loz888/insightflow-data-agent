import pytest
from insightflow.database.metadata import read_catalog
from insightflow.llm.base import Plan
from insightflow.retrieval.retriever import SchemaRetriever
from insightflow.database.errors import AgentError


@pytest.mark.integration
def test_retrieval_ranking_selection_join_context(database_urls):
    retriever = SchemaRetriever(read_catalog(database_urls[0]))
    simple = retriever.retrieve("商品平均价格是多少？", Plan(metric="average_price"))
    assert simple["retrieved_tables"] == ["products"]
    assert "refunds" not in simple["retrieved_tables"]
    result = retriever.retrieve("各商品类别销售收入比较", Plan(metric="paid_revenue", group="category"))
    assert set(result["retrieved_tables"]) == {"orders", "order_items", "products"}
    assert "customers" not in result["retrieved_tables"]
    assert all("." in c for c in result["retrieved_columns"])
    assert result["retrieved_metrics"]["paid_revenue"]
    assert result["retrieval_scores"]["order_items"] > result["retrieval_scores"]["refunds"]
    assert not any("pg_" in n for n in result["retrieved_tables"])


@pytest.mark.integration
def test_retrieval_cannot_drop_necessary_join(database_urls):
    retriever = SchemaRetriever(read_catalog(database_urls[0]), max_items=1)
    with pytest.raises(AgentError):
        retriever.retrieve("收入", Plan(metric="paid_revenue"))


def test_unknown_metric_cannot_be_invented():
    with pytest.raises(ValueError):
        Plan(metric="employee_churn")
