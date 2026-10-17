import argparse
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.evaluation.scorer import equivalent, exact_sql, grounded, summarize
from insightflow.evaluation.report import save_report

ROOT = Path(__file__).resolve().parents[3]


def run_evaluation(service, cases):
    records = []
    for case in cases:
        session_id = "eval-" + uuid4().hex
        started = time.perf_counter()
        turns = []
        for question in case.get("history", []):
            turns.append(service.run(question, session_id))
        result = service.run(case["question"], session_id)
        turns.append(result)
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        executed = "query_result" in result and result.get("error") is None
        correct = executed and equivalent(
            result["query_result"], case["expected_result"], case.get("ordered", False)
        )
        inherited = all(
            result.get("plan", {}).get(k) == v for k, v in case.get("expected_constraints", {}).items()
        )
        metric = result.get("plan", {}).get("metric") == case["expected_metric"]
        answer_grounded = False
        if executed:
            independent = service.executor.execute(result["generated_sql"])
            answer_grounded = grounded(result["final_answer"], independent)
        error = result.get("error", {}).get("kind") if result.get("error") else None
        success = bool(
            executed
            and correct
            and answer_grounded
            and inherited
            and metric
            and all(t.get("error") is None for t in turns)
        )
        if not success and not error:
            error = "RESULT_MISMATCH" if not correct else "EVIDENCE_OR_CONTEXT_MISMATCH"
        usage_known = all(t["usage"]["token_usage_known"] for t in turns)
        records.append(
            {
                "case_id": case["case_id"],
                "run_id": result["request_id"],
                "model_type": service.provider.model_type,
                "sql_valid": result.get("validation_result", {}).get("valid", False),
                "sql_executed": executed,
                "sql_exact_match": exact_sql(result.get("generated_sql", ""), case["reference_sql"]),
                "result_correct": bool(correct),
                "answer_grounded": answer_grounded,
                "scenario_success": success,
                "constraints_correct": inherited and metric,
                "retries": sum(t["retry_count"] for t in turns),
                "duration_ms": elapsed,
                "model_calls": sum(t["model_calls"] for t in turns),
                "input_tokens": sum(t["usage"]["input_tokens"] for t in turns) if usage_known else None,
                "output_tokens": sum(t["usage"]["output_tokens"] for t in turns) if usage_known else None,
                "token_usage_known": usage_known,
                "error_kind": error,
                "generated_sql": result.get("generated_sql", ""),
                "observed_result": result.get("query_result"),
                "expected_result": case["expected_result"],
            }
        )
    return records, summarize(records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    settings = Settings(database_url=SecretStr(os.environ["INSIGHTFLOW_TEST_DATABASE_URL"]), mode="mock")
    from insightflow.database.connection import checked_connection

    with checked_connection(settings.database_url.get_secret_value(), test_only=True):
        pass
    service = AgentService(settings)
    try:
        cases = json.loads((ROOT / "evaldata/questions.json").read_text())
        records, summary = run_evaluation(service, cases)
        save_report(args.output, records, summary)
        print(json.dumps(summary, ensure_ascii=False))
        return 1 if args.strict and summary["success_rate"] < 1 else 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
