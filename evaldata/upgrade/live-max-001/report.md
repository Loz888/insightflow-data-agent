# V2 实测评测

~~~json
{
  "mode": "deepseek",
  "model": "deepseek-flash",
  "thinking_effort": "max",
  "at": "2026-10-17T10:01:00.243314+00:00",
  "git_commit": "b91db24d2402214cd2b4c7b312be90f70164e9e6",
  "source_sha256": "b9f836594fc73bb86cddb850aa5b77be28ddf8d73cf71bbf9a8710c10b2b03a5",
  "prompt_version": "insightflow-agent-v3-20261017",
  "data_version": "v1-seed20261020",
  "dataset_sha256": "c30d189525328ad731fc75cfe41e3e16f0505546e2761d301b875ef789a4c17c",
  "execution": {
    "correct": 22,
    "total": 26
  },
  "result_accuracy": {
    "correct": 22,
    "total": 26
  },
  "semantic_accuracy": {
    "correct": 22,
    "total": 26
  },
  "clarification_rejection": {
    "correct": 3,
    "total": 4
  },
  "evidence_consistency": {
    "correct": 22,
    "total": 26
  },
  "e2e": {
    "correct": 25,
    "total": 30
  },
  "not_run_budget": 0,
  "p50_ms": 12361.969747999865,
  "p95_ms": 20828.96677100007,
  "budget": {
    "experiment_id": "upgrade-v2-20261017",
    "budget": "2.00",
    "reserved": "0.2006037",
    "attempts": 165
  },
  "usage_unknown_runs": 1,
  "limitations": [
    "Test questions were inspected during development; frozen_seen is not an unseen benchmark.",
    "Automatic natural-language evidence checking is limited; representative human review is separate.",
    "No causal or production-scale inference."
  ]
}
~~~
