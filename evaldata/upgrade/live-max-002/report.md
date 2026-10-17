# V2 实测评测

~~~json
{
  "mode": "deepseek",
  "retrieval_mode": "rules",
  "context_enabled": true,
  "feedback_enabled": true,
  "model": "deepseek-flash",
  "thinking_effort": "max",
  "at": "2026-10-17T10:14:42.920356+00:00",
  "git_commit": "dff9ac3502ff5c9480360ef454f0a9ba436a276f",
  "source_sha256": "8ef866ffbd82e7629198582aa1139e2d7e361f67eec235ba4a1461c72ef83c51",
  "prompt_version": "insightflow-agent-v3-20261017",
  "data_version": "v1-seed20261020",
  "dataset_sha256": "c30d189525328ad731fc75cfe41e3e16f0505546e2761d301b875ef789a4c17c",
  "execution": {
    "correct": 23,
    "total": 26
  },
  "result_accuracy": {
    "correct": 23,
    "total": 26
  },
  "semantic_accuracy": {
    "correct": 23,
    "total": 26
  },
  "clarification_rejection": {
    "correct": 4,
    "total": 4
  },
  "evidence_consistency": {
    "correct": 23,
    "total": 26
  },
  "e2e": {
    "correct": 27,
    "total": 30
  },
  "not_run_budget": 0,
  "p50_ms": 11671.70297299981,
  "p95_ms": 23615.465704000144,
  "budget": {
    "experiment_id": "upgrade-v2-20261017",
    "budget": "2.00",
    "reserved": "0.3425010",
    "attempts": 318
  },
  "usage_unknown_runs": 0,
  "limitations": [
    "Test questions were inspected during development; frozen_seen is not an unseen benchmark.",
    "Automatic natural-language evidence checking is limited; representative human review is separate.",
    "No causal or production-scale inference."
  ]
}
~~~
