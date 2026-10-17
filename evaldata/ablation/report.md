# Retrieval / Context ablation

Mock + real PostgreSQL. Same 30 cases, snapshot, Prompt base, retry policy and SQL security for all modes.
Fixed minimal Schema contains only orders; dynamic selection uses reviewed metadata, K=5.
Recall labels are independently reviewed physical ReferenceSQL tables, not generated SQL.
Recall denominator includes understanding/context failures (empty selection).

| Mode | Recall@5 | SQL result | Grounded | Context | E2E | Avg context estimate | Calls | P50 / P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| baseline | 0.344 | 0.833 | 0.833 | 0.833 | 0.833 | 280.4 | 65 | 13.287 / 17.742 |
| retrieval_only | 0.833 | 0.833 | 0.833 | 0.833 | 0.833 | 657.9 | 65 | 12.469 / 16.153 |
| context_only | 0.411 | 1.000 | 1.000 | 1.000 | 1.000 | 288.4 | 70 | 11.052 / 23.411 |
| full | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 695.9 | 70 | 10.651 / 21.937 |

Mock SQL rules do not read Schema text; retrieval alone cannot prove LLM accuracy improvement.
Context differences demonstrate deterministic constraint inheritance only. Full is not assumed superior.
Token usage unknown in every Mock mode; context size is an estimate, not measured model Token.
Latency is a small sequential sample; real paid-model ablation NOT_RUN. Failures remain in failures.json.
