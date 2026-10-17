# V2 实测评测

~~~json
{
  "mode": "mock",
  "retrieval_mode": "rules",
  "context_enabled": true,
  "feedback_enabled": true,
  "model": "offline-rules",
  "thinking_effort": null,
  "at": "2026-10-17T10:21:36.003480+00:00",
  "git_commit": "889f654dcf7ddc75d3e33d9253c1b7f721690059",
  "source_sha256": "3e6bb0fccf741a7ef9afc4075f4e0540f36364c6402caea16bb0bf8fd7361cf5",
  "prompt_version": "insightflow-agent-v3-20261017",
  "data_version": "v1-seed20261020",
  "dataset_sha256": "c30d189525328ad731fc75cfe41e3e16f0505546e2761d301b875ef789a4c17c",
  "execution": {
    "correct": 55,
    "total": 55
  },
  "result_accuracy": {
    "correct": 55,
    "total": 55
  },
  "semantic_accuracy": {
    "correct": 55,
    "total": 55
  },
  "clarification_rejection": {
    "correct": 20,
    "total": 20
  },
  "evidence_consistency": {
    "correct": 55,
    "total": 55
  },
  "e2e": {
    "correct": 87,
    "total": 87
  },
  "not_run_budget": 0,
  "p50_ms": 176.23306499990576,
  "p95_ms": 250.96675699978732,
  "budget": {
    "experiment_id": "upgrade-v2-20261017",
    "budget": "2.00",
    "reserved": "0.4741200",
    "attempts": 456
  },
  "usage_unknown_runs": 0,
  "limitations": [
    "Test questions were inspected during development; frozen_seen is not an unseen benchmark.",
    "Automatic natural-language evidence checking is limited; representative human review is separate.",
    "No causal or production-scale inference."
  ]
}
~~~
