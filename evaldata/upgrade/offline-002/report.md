# V2 实测评测

~~~json
{
  "mode": "mock",
  "model": "offline-rules",
  "thinking_effort": null,
  "at": "2026-10-17T09:54:30.240397+00:00",
  "git_commit": "04068775ac2c8c7ac943a300405617368b92f04c",
  "source_sha256": "22d0bdf47ccaf345a272f35eda34ad4c9e16677f16a0730efbac19bf925e176c",
  "prompt_version": "insightflow-agent-v3-20261017",
  "data_version": "v1-seed20261020",
  "dataset_sha256": "c30d189525328ad731fc75cfe41e3e16f0505546e2761d301b875ef789a4c17c",
  "execution": {
    "correct": 50,
    "total": 50
  },
  "result_accuracy": {
    "correct": 50,
    "total": 50
  },
  "semantic_accuracy": {
    "correct": 50,
    "total": 50
  },
  "clarification_rejection": {
    "correct": 20,
    "total": 20
  },
  "evidence_consistency": {
    "correct": 50,
    "total": 50
  },
  "e2e": {
    "correct": 82,
    "total": 82
  },
  "not_run_budget": 0,
  "p50_ms": 161.35376000011092,
  "p95_ms": 225.96899100017254,
  "budget": {
    "experiment_id": "upgrade-v2-20261017",
    "budget": "2.00",
    "reserved": "0.0532386",
    "attempts": 17
  },
  "usage_unknown_runs": 0,
  "limitations": [
    "Test questions were inspected during development; frozen_seen is not an unseen benchmark.",
    "Automatic natural-language evidence checking is limited; representative human review is separate.",
    "No causal or production-scale inference."
  ]
}
~~~
