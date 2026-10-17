import json
from pathlib import Path
import pytest
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.evaluation.performance import percentile, run_profile, plans


def test_percentile_and_no_fabricated_timeout_values():
    assert percentile(list(range(1, 101)), 0.5) == 50
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert percentile(list(range(1, 101)), 0.99) == 99
    with pytest.raises(ValueError):
        percentile([], 0.95)


@pytest.mark.integration
def test_actual_stage_trace_is_redacted(database_urls, caplog):
    caplog.set_level("INFO", logger="insightflow.trace")
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    try:
        state = svc.run("2026年9月退款率是多少？", "private-session-identifier")
        assert state["total_duration_ms"] > 0
        for key in (
            "retrieval_duration_ms",
            "context_duration_ms",
            "llm_duration_ms",
            "validation_duration_ms",
            "sql_duration_ms",
            "answer_duration_ms",
        ):
            assert state["timings"][key] > 0
        assert len(state["node_events"]) == 6
        assert all(
            e["duration_ms"] >= 0 and e["request_id"] == state["request_id"] for e in state["node_events"]
        )
        events = [
            json.loads(record.message) for record in caplog.records if record.name == "insightflow.trace"
        ]
        assert any(e["tool_name"] == "execute_readonly_sql" for e in events)
        text = "\n".join(record.message for record in caplog.records)
        assert "private-session-identifier" not in text
        assert "SELECT" not in text and "2026年9月退款率" not in text
        assert database_urls[0] not in text
        assert all(e["session_id"].startswith("sha256:") for e in events)
    finally:
        svc.close()


@pytest.mark.integration
def test_real_profile_unique_ids_and_controlled_plans(database_urls):
    cases = json.loads((Path(__file__).resolve().parents[1] / "evaldata/questions.json").read_text())[:2]
    records, summary = run_profile(database_urls[0], cases, 2, requests=8)
    assert summary["requests"] == summary["completed"] == summary["succeeded"] == 8
    assert summary["failed"] == 0 and len({r["run_id"] for r in records}) == 8
    assert summary["throughput_requests_per_second"] > 0 and summary["p95_ms"] >= summary["p50_ms"]
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    try:
        result = plans(database_urls[0], svc.executor.validator)
        assert set(result) == {"single_filter", "join_group", "time_aggregate"}
        assert all(item["plan"][0]["Execution Time"] >= 0 for item in result.values())
        assert all("Shared Hit Blocks" in item["plan"][0]["Plan"] for item in result.values())
    finally:
        svc.close()


@pytest.mark.integration
def test_request_trace_retains_actual_retry_count(database_urls, caplog):
    from insightflow.llm.mock import MockLLMProvider
    from insightflow.llm.base import Generation

    class Broken(MockLLMProvider):
        def generate(self, *args):
            return Generation(sql="SELECT missing FROM business.orders")

    caplog.set_level("INFO", logger="insightflow.trace")
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])), Broken())
    try:
        state = svc.run("订单数是多少？")
        final = [
            json.loads(record.message)
            for record in caplog.records
            if record.name == "insightflow.trace" and json.loads(record.message)["node_name"] == "Request"
        ][-1]
        assert final["retry_count"] == state["retry_count"] == 2
        assert final["error_kind"] == "BUDGET_EXHAUSTED"
    finally:
        svc.close()
