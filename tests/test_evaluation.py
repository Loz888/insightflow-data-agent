import json
from pathlib import Path
import pytest
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.evaluation.runner import run_evaluation
from insightflow.evaluation.scorer import equivalent, grounded, exact_sql
from insightflow.evaluation.report import save_report


def test_comparison_not_exact_sql_or_execution_only():
    left = {"columns": ["value"], "column_types": ["numeric"], "rows": [["1.00000000001"], ["2"]]}
    right = {"columns": ["value"], "column_types": ["numeric"], "rows": [[2], [1]]}
    assert equivalent(left, right)
    assert not equivalent(left, right, ordered=True)
    assert not equivalent({"columns": ["value"], "rows": [[999]]}, {"columns": ["value"], "rows": [[1]]})
    assert not exact_sql("SELECT id FROM business.orders", "SELECT o.id FROM business.orders o")
    assert not equivalent({"columns": ["value"], "rows": [[None]]}, {"columns": ["value"], "rows": [[0]]})


def test_groundedness_detects_fabrication():
    result = {"columns": ["value"], "rows": [[500]]}
    answer = {"answer": "查询结果：" + json.dumps(result), "evidence": result}
    assert grounded(answer, result)
    assert not grounded({**answer, "answer": "收入是 99999，证明政策导致增长"}, result)
    assert not grounded({**answer, "evidence": {"columns": ["value"], "rows": [[1]]}}, result)


@pytest.mark.integration
def test_all_30_cases_have_actual_observations(database_urls, tmp_path):
    cases = json.loads((Path(__file__).resolve().parents[1] / "evaldata/questions.json").read_text())
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    try:
        records, summary = run_evaluation(svc, cases)
        assert len(records) == 30 and len({r["run_id"] for r in records}) == 30
        assert all(r["sql_executed"] for r in records), [
            (r["case_id"], r["error_kind"]) for r in records if r["error_kind"]
        ]
        # Result correctness comes from independent reference data, not SQL text.
        assert all(r["result_correct"] and r["answer_grounded"] and r["constraints_correct"] for r in records)
        assert summary["real_deepseek"] == "NOT RUN"
        assert summary["input_tokens"] is None and summary["token_usage_known_cases"] == 0
        assert summary["model_call_count"] == 70
        save_report(tmp_path, records, summary)
        assert len((tmp_path / "runs.jsonl").read_text().splitlines()) == 30
        assert json.loads((tmp_path / "failures.json").read_text()) == []
    finally:
        svc.close()


@pytest.mark.integration
def test_wrong_but_executable_sql_remains_failure(database_urls, tmp_path):
    from insightflow.llm.mock import MockLLMProvider
    from insightflow.llm.base import Generation

    class Wrong(MockLLMProvider):
        def generate(self, *args):
            return Generation(sql="SELECT count(*) AS value FROM business.products")

    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])), Wrong())
    try:
        case = json.loads((Path(__file__).resolve().parents[1] / "evaldata/questions.json").read_text())[0]
        records, summary = run_evaluation(svc, [case])
        assert records[0]["sql_executed"] and records[0]["answer_grounded"]
        assert not records[0]["result_correct"] and not records[0]["scenario_success"]
        assert records[0]["error_kind"] == "RESULT_MISMATCH"
        save_report(tmp_path, records, summary)
        assert len(json.loads((tmp_path / "failures.json").read_text())) == 1
    finally:
        svc.close()
