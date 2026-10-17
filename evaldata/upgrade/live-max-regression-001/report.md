# V2 实测评测

~~~json
{
  "mode": "deepseek",
  "retrieval_mode": "rules",
  "context_enabled": true,
  "feedback_enabled": true,
  "model": "deepseek-flash",
  "thinking_effort": "max",
  "at": "2026-10-17T10:17:35.949401+00:00",
  "git_commit": "889f654dcf7ddc75d3e33d9253c1b7f721690059",
  "source_sha256": "3e6bb0fccf741a7ef9afc4075f4e0540f36364c6402caea16bb0bf8fd7361cf5",
  "prompt_version": "insightflow-agent-v3-20261017",
  "data_version": "v1-seed20261020",
  "dataset_sha256": "c30d189525328ad731fc75cfe41e3e16f0505546e2761d301b875ef789a4c17c",
  "execution": {
    "correct": 6,
    "total": 7
  },
  "result_accuracy": {
    "correct": 6,
    "total": 7
  },
  "semantic_accuracy": {
    "correct": 6,
    "total": 7
  },
  "clarification_rejection": {
    "correct": 2,
    "total": 2
  },
  "evidence_consistency": {
    "correct": 6,
    "total": 7
  },
  "e2e": {
    "correct": 8,
    "total": 9
  },
  "not_run_budget": 0,
  "p50_ms": 10141.01089099995,
  "p95_ms": 26162.166135999996,
  "budget": {
    "experiment_id": "upgrade-v2-20261017",
    "budget": "2.00",
    "reserved": "0.3824241",
    "attempts": 363
  },
  "usage_unknown_runs": 0,
  "limitations": [
    "Test questions were inspected during development; frozen_seen is not an unseen benchmark.",
    "Automatic natural-language evidence checking is limited; representative human review is separate.",
    "No causal or production-scale inference."
  ]
}
~~~
