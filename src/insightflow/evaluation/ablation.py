import argparse
import hashlib
import json
import os
from pathlib import Path
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.evaluation.runner import ROOT, run_evaluation

MODES = ("baseline", "retrieval_only", "context_only", "full")


def experiment(dsn, cases, labels):
    all_records = []
    summaries = {}
    for mode in MODES:
        service = AgentService(Settings(database_url=SecretStr(dsn), experiment_mode=mode))
        try:
            records, summary = run_evaluation(service, cases)
        finally:
            service.close()
        for record in records:
            gold = set(labels["cases"][record["case_id"]])
            predicted = set(record["selected_tables"][: labels["k"]])
            record["recall_at_k"] = len(gold & predicted) / len(gold)
            record["mode"] = mode
        sizes = [r["context_size_estimate"] for r in records if r["context_size_estimate"] is not None]
        summary.update(
            recall_at_k=sum(r["recall_at_k"] for r in records) / len(records),
            k=labels["k"],
            context_correctness=sum(r["constraints_correct"] for r in records) / len(records),
            average_context_size_estimated=sum(sizes) / len(sizes) if sizes else None,
            measured_contexts=len(sizes),
            average_selected_tables=sum(len(r["selected_tables"]) for r in records) / len(records),
        )
        summaries[mode] = summary
        all_records.extend(records)
    return all_records, summaries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    cases = json.loads((ROOT / "evaldata/questions.json").read_text())
    labels = json.loads((ROOT / "evaldata/retrieval_labels.json").read_text())
    assert (
        labels["source_sha256"] == hashlib.sha256((ROOT / "evaldata/questions.json").read_bytes()).hexdigest()
    )
    from insightflow.database.connection import checked_connection

    dsn = os.environ["INSIGHTFLOW_TEST_DATABASE_URL"]
    with checked_connection(dsn, test_only=True):
        pass
    records, summary = experiment(dsn, cases, labels)
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    (out / "failures.json").write_text(
        json.dumps([r for r in records if not r["scenario_success"]], ensure_ascii=False, indent=2) + "\n"
    )
    lines = [
        "# Retrieval / Context ablation",
        "",
        "Mock + real PostgreSQL. Same 30 cases, snapshot, Prompt base, retry policy and SQL security for all modes.",
        "Fixed minimal Schema contains only orders; dynamic selection uses reviewed metadata, K=5.",
        "Recall labels are independently reviewed physical ReferenceSQL tables, not generated SQL.",
        "Recall denominator includes understanding/context failures (empty selection).",
        "",
        "| Mode | Recall@5 | SQL result | Grounded | Context | E2E | Avg context estimate | Calls | P50 / P95 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for mode, s in summary.items():
        lines.append(
            f"| {mode} | {s['recall_at_k']:.3f} | {s['sql_result_accuracy']:.3f} | {s['answer_groundedness']:.3f} | {s['context_correctness']:.3f} | {s['success_rate']:.3f} | {s['average_context_size_estimated']:.1f} | {s['model_call_count']} | {s['p50_ms']} / {s['p95_ms']} |"
        )
    lines += [
        "",
        "Mock SQL rules do not read Schema text; retrieval alone cannot prove LLM accuracy improvement.",
        "Context differences demonstrate deterministic constraint inheritance only. Full is not assumed superior.",
        "Token usage unknown in every Mock mode; context size is an estimate, not measured model Token.",
        "Latency is a small sequential sample; real paid-model ablation NOT_RUN. Failures remain in failures.json.",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                m: {"success_rate": s["success_rate"], "recall_at_k": s["recall_at_k"]}
                for m, s in summary.items()
            }
        )
    )


if __name__ == "__main__":
    main()
