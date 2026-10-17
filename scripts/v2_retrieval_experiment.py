import json
import os
from pathlib import Path
from dotenv import dotenv_values
from insightflow.v2.contracts import QueryPlan
from insightflow.v2.retrieval import Retriever
from insightflow.v2.semantics import AGGREGATIONS

ROOT = Path(__file__).resolve().parents[1]
d = {**dotenv_values(ROOT / ".env"), **os.environ}
retriever = Retriever(d["INSIGHTFLOW_TEST_DATABASE_URL"])
labels = json.loads((ROOT / "evaldata/v2/retrieval_labels.json").read_text())
results = []
for mode in ("full", "rules", "lexical"):
    runs = []
    for case in labels:
        plan = QueryPlan(metric=case["metric"], aggregation=AGGREGATIONS[case["metric"]])
        observed = retriever.select(case["question"], plan, mode)
        a = set(observed["selected_tables"])
        b = set(case["tables"])
        intersection = len(a & b)
        runs.append(
            {
                "question": case["question"],
                "expected": sorted(b),
                "selected": sorted(a),
                "recall": intersection / len(b),
                "precision": intersection / len(a),
                "context_bytes": observed["context_bytes"],
                "estimated_token_upper_bound": observed["estimated_tokens_upper_bound"],
            }
        )
    results.append(
        {
            "mode": mode,
            "recall": sum(r["recall"] for r in runs) / len(runs),
            "precision": sum(r["precision"] for r in runs) / len(runs),
            "mean_context_bytes": sum(r["context_bytes"] for r in runs) / len(runs),
            "runs": runs,
        }
    )
out = ROOT / "evaldata/upgrade/retrieval-quality-001"
out.mkdir(exist_ok=False)
(out / "results.json").write_text(
    json.dumps(
        {
            "authorized_tables": list(retriever.tables),
            "schema_version": retriever.version,
            "results": results,
            "limitation": "Retrieval quality only; real-model effect is a separately paired experiment. Token bounds are not usage.",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
print(json.dumps([{k: v for k, v in x.items() if k != "runs"} for x in results]))
