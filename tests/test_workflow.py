from pathlib import Path
import json
import pytest
from pydantic import SecretStr
from insightflow.config import Settings
from insightflow.agent.service import AgentService
from insightflow.llm.mock import MockLLMProvider
from insightflow.llm.base import Generation


@pytest.fixture
def service(database_urls):
    value = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    yield value
    value.close()


@pytest.mark.integration
def test_ten_real_graph_queries(service):
    cases = json.loads((Path(__file__).resolve().parents[1] / "evaldata/questions.json").read_text())
    for case in cases[:10] + cases[10:13] + cases[20:24]:
        result = service.run(case["question"])
        assert result["error"] is None, (case["case_id"], result["error"])
        assert result["query_result"]["rows"] == case["expected_result"]["rows"]
        assert result["trace"] == [
            "UnderstandQuestion",
            "SelectSchema",
            "GenerateSQL",
            "ValidateSQL",
            "ExecuteSQL",
            "GenerateAnswer",
        ]
        assert result["final_answer"]["evidence"] == result["query_result"]
        assert result["model_calls"] == 2
    assert "ClassifyFailure" in service.graph.get_graph().nodes


@pytest.mark.integration
def test_retry_budget_and_safety(database_urls):
    class Broken(MockLLMProvider):
        def __init__(self, sql):
            self.sql = sql

        def generate(self, *args):
            return Generation(sql=self.sql)

    for sql, kind, retries in [
        ("SELECT missing_column FROM business.orders", "BUDGET_EXHAUSTED", 2),
        ("DROP TABLE business.orders", "SQL_VALIDATION_ERROR", 0),
    ]:
        svc = AgentService(Settings(database_url=SecretStr(database_urls[0])), Broken(sql))
        try:
            result = svc.run("订单总数是多少？")
            assert result["error"]["kind"] == kind, result
            assert result["retry_count"] == retries
            assert not result.get("query_result")
            assert result["final_answer"]["evidence"] == {}
            assert result["trace"].count("GenerateSQL") == retries + 1
        finally:
            svc.close()


@pytest.mark.integration
def test_recoverable_feedback(database_urls):
    class Repair(MockLLMProvider):
        def generate(self, plan, context, feedback):
            return Generation(
                sql="SELECT count(*) AS value FROM business.orders"
                if feedback
                else "SELECT bad FROM business.orders"
            )

    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])), Repair())
    try:
        result = svc.run("订单总数是多少？")
        assert result["error"] is None and result["retry_count"] == 1
        assert result["query_result"]["rows"] == [[500]]
    finally:
        svc.close()


@pytest.mark.integration
def test_no_evidence_no_fake_answer(service):
    result = service.run("为什么员工离职率上升？")
    assert result["error"]["kind"] == "CLARIFICATION_REQUIRED"
    assert result["final_answer"]["evidence"] == {}
