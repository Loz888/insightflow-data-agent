"""A small real-model experiment. Gate is read, never enabled by this program."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from pydantic import SecretStr
from insightflow.config import Settings
from insightflow.agent.service import AgentService
from insightflow.evaluation.runner import ROOT, run_evaluation
from insightflow.evaluation.report import save_report
from insightflow.llm.deepseek import PROMPT_VERSION


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    reason = None
    if os.environ.get("INSIGHTFLOW_ENABLE_PAID_EVAL") != "1":
        reason = "PAID_EVAL_NOT_AUTHORIZED"
    elif os.environ.get("INSIGHTFLOW_ENABLE_LIVE", "false").lower() != "true":
        reason = "LIVE_MODE_DISABLED"
    elif not os.environ.get("DEEPSEEK_API_KEY"):
        reason = "KEY_NOT_CONFIGURED"
    selection = json.loads((ROOT / "evaldata/real_model/cases.json").read_text())
    assert (
        selection["source_sha256"]
        == hashlib.sha256((ROOT / "evaldata/questions.json").read_bytes()).hexdigest()
    )
    if reason:
        summary = {
            "status": "NOT_RUN",
            "reason": reason,
            "model_type": "deepseek",
            "cases_selected": len(selection["case_ids"]),
            "prompt_version": PROMPT_VERSION,
            "api_calls": 0,
            "sql_result_accuracy": None,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "usage_known": False,
            "latency_ms": None,
        }
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (out / "runs.jsonl").write_text("")
        (out / "report.md").write_text(
            "# Real model evaluation\n\nNOT_RUN: "
            + reason
            + "\n\nNo paid request was sent. No capability, token or latency result is claimed.\n"
        )
        print("REAL_MODEL_EVALUATION = NOT_RUN: " + reason)
        return 0
    from insightflow.database.connection import checked_connection

    dsn = os.environ["INSIGHTFLOW_TEST_DATABASE_URL"]
    with checked_connection(dsn, test_only=True):
        pass
    service = AgentService(Settings(database_url=SecretStr(dsn), mode="deepseek"))
    try:
        cases = [
            c
            for c in json.loads((ROOT / "evaldata/questions.json").read_text())
            if c["case_id"] in selection["case_ids"]
        ]
        records, summary = run_evaluation(service, cases)
        summary.update(
            status="RUN",
            prompt_version=PROMPT_VERSION,
            api_calls=service.provider.calls,
            reserved_cost_usd=str(service.provider.spent),
            max_calls=service.provider.max_calls,
            max_output_tokens=service.provider.max_output_tokens,
            request_timeout_seconds=service.provider.timeout,
            cost_measurement="conservative reservation, not an exact billing cap",
        )
        save_report(out, records, summary)
        print(json.dumps(summary))
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
