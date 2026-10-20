"""Replay recorded result comparisons only. No provider, network or database is used.
Historical warmup/semantic/grounding flags are retained, not invented from missing traces.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from insightflow.evaluation.scorer import SCORER_VERSION, equivalent

ROOT = Path(__file__).resolve().parents[1]
# Independent, frozen result-layout contract for this project's supported metric dataset.
# Never derive the type from the model's SQL or observed value.
LAYOUTS = {
    ("value",): ["numeric"],
    ("dimension", "value"): ["text", "numeric"],
    ("current", "previous", "change_rate"): ["numeric"] * 3,
}


def typed_reference(reference):
    columns = tuple(reference.get("columns", []))
    if columns not in LAYOUTS:
        raise ValueError("Recorded result layout has no frozen type contract")
    return {**reference, "column_types": LAYOUTS[columns]}


def replay_dataset(path, cases):
    raw = path.read_bytes()
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    counts = Counter()
    changes = []
    for rec in rows:
        if "observed_result" in rec and "expected_result" in rec:
            actual, reference = rec["observed_result"], rec["expected_result"]
            ordered = cases.get(rec["case_id"], {}).get("ordered", False)
            executed = rec.get("sql_executed", False)
        elif rec.get("expected") == "answer" and rec.get("reference"):
            actual, reference = (rec.get("result") or {}).get("evidence"), rec["reference"]
            ordered, executed = True, rec.get("sql_executed", False)
        else:
            counts["not_a_recorded_query_comparison"] += 1
            continue
        score = bool(executed and actual and equivalent(actual, typed_reference(reference), ordered))
        old = bool(rec["result_correct"])
        counts["comparisons"] += 1
        counts["old_correct"] += old
        counts["new_correct"] += score
        if old != score:
            changes.append({"case_id": rec["case_id"], "old": old, "new": score, "field": "result_correct"})
        for snap in rec.get("cross_snapshot_results", []):
            score = equivalent(snap["actual"], typed_reference(snap["expected"]), ordered=True)
            counts["snapshot_comparisons"] += 1
            if bool(snap["correct"]) != score:
                changes.append(
                    {
                        "case_id": rec["case_id"],
                        "dataset": snap["dataset"],
                        "old": bool(snap["correct"]),
                        "new": score,
                        "field": "snapshot_result_correct",
                    }
                )
    return {
        "source": str(path.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "records": len(rows),
        **dict(counts),
        "changed": len(changes),
        "changes": changes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists():
        raise SystemExit("Refuse to overwrite an existing replay report")
    golden = ROOT / "evaldata/questions.json"
    golden_hash = hashlib.sha256(golden.read_bytes()).hexdigest()
    cases = {x["case_id"]: x for x in json.loads(golden.read_text())}
    reports = [
        replay_dataset(path, cases) for path in sorted((ROOT / "evaldata/upgrade").rglob("runs.jsonl"))
    ]
    if hashlib.sha256(golden.read_bytes()).hexdigest() != golden_hash:
        raise RuntimeError("Frozen original cases changed during replay")
    summary = {
        "scorer_version": SCORER_VERSION,
        "mode": "recorded-result-replay; no model or database calls",
        "paid_calls": 0,
        "golden_sha256": golden_hash,
        "type_contracts": {"|".join(k): v for k, v in LAYOUTS.items()},
        "datasets": reports,
        "total_result_comparisons": sum(x.get("comparisons", 0) for x in reports),
        "total_snapshot_comparisons": sum(x.get("snapshot_comparisons", 0) for x in reports),
        "changed_comparisons": sum(x["changed"] for x in reports),
        "limits": [
            "Only result comparison flags are recomputed; historical E2E/warmup/grounding claims are not reconstructed from incomplete traces.",
            "Frozen metric layouts provide reference types for old artifacts without PostgreSQL OIDs.",
            "This replay does not measure current-model quality or latency.",
        ],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "scorer_version",
                    "total_result_comparisons",
                    "total_snapshot_comparisons",
                    "changed_comparisons",
                    "paid_calls",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
