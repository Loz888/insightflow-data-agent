"""Explicitly authorized local experiments; all arms share one durable project budget."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from dotenv import dotenv_values
from insightflow.v2.api import load_settings
from insightflow.v2.evaluation import run_cases

ROOT = Path(__file__).resolve().parents[1]


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["regression", "paired"], required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    d = {**dotenv_values(ROOT / ".env"), **os.environ}
    base = load_settings()
    config = {
        **base.model_dump(),
        "mode": "deepseek",
        "live_enabled": True,
        "runtime_url": d["INSIGHTFLOW_V2_TEST_RUNTIME_URL"],
        "reader_url": d["INSIGHTFLOW_TEST_DATABASE_URL"],
    }
    base = type(base).model_validate(config)
    all_cases = json.loads((ROOT / "evaldata/v2/cases.json").read_text()) + json.loads(
        (ROOT / "evaldata/v2/additional_cases.json").read_text()
    )
    cases = {c["id"]: c for c in all_cases}
    snapshot = {f"v2-seed{n}": d[f"INSIGHTFLOW_V2_SEED{n}_URL"] for n in (101, 202)}
    out = Path(args.output)
    if args.phase == "regression":
        selected = [cases[f"v2-{n:03d}"] for n in (26, 34, 36, 46, 48, 51, 70, 83, 86)]
        summary = await run_cases(base, out, selected, False, snapshot)
        print(json.dumps(summary, ensure_ascii=False, default=str))
        return
    out.mkdir(parents=True, exist_ok=False)
    summaries = []
    groups = [
        (
            "schema",
            ["v2-031", "v2-083"],
            [("selected", {"retrieval_mode": "rules"}), ("full", {"retrieval_mode": "full"})],
            False,
        ),
        (
            "context",
            ["v2-046", "v2-048"],
            [("with_context", {"context_enabled": True}), ("without_context", {"context_enabled": False})],
            False,
        ),
        (
            "feedback",
            ["v2-001", "v2-028"],
            [
                ("with_feedback", {"feedback_enabled": True}),
                ("without_feedback", {"feedback_enabled": False}),
            ],
            True,
        ),
    ]
    for group, ids, arms, fault in groups:
        for arm, changes in arms:
            config = type(base).model_validate({**base.model_dump(), **changes})
            selected = [{**cases[n], "controlled_fault": fault} for n in ids]
            summary = await run_cases(config, out / (group + "-" + arm), selected, fault, snapshot)
            summaries.append(
                {
                    "group": group,
                    "arm": arm,
                    "n": len(selected),
                    "controlled_fault": fault,
                    "summary": summary,
                }
            )
    (out / "summary.json").write_text(
        json.dumps(
            {
                "experiments": summaries,
                "uncertainty": "Only two inspected cases per arm, fixed order, stochastic vendor outputs; descriptive paired observations, no significance or universal causal claim.",
                "shared_experiment_id": base.experiment_id,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n"
    )
    print(
        json.dumps(
            [
                {k: v for k, v in x.items() if k != "summary"} | {"e2e": x["summary"]["e2e"]}
                for x in summaries
            ],
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
