# Performance experiment

{"platform": "Linux/WSL", "python": "3.12.3", "postgresql": "16.15 (Ubuntu 16.15-0ubuntu0.24.04.1)", "cpu": "AMD Ryzen AI 9 H 365 w/ Radeon 880M", "logical_cpus": 20, "visible_memory_kib": "14111404", "dataset": {"customers": 100, "products": 30, "orders": 500, "order_items": 1001, "refunds": 165}, "model": "mock", "entrypoint": "AgentService.run (not HTTP throughput)", "warm_cache": true, "percentile": "nearest rank ceil(n*p)-1", "session_policy": "global serialized lock", "snapshot": "fixed synthetic seed 20261020"}

| Concurrency | Requests | Completed | Succeeded | Failed | req/s | P50 ms | P95 ms | P99 ms | Queue avg ms | SQL avg ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 128 | 128 | 128 | 0 | 86.71 | 11.621 | 14.484 | 16.047 | 0.028 | 6.915 |
| 2 | 128 | 128 | 128 | 0 | 80.91 | 22.871 | 28.744 | 68.472 | 10.819 | 7.409 |
| 4 | 128 | 128 | 128 | 0 | 83.69 | 45.726 | 53.063 | 54.946 | 34.178 | 7.068 |
| 8 | 128 | 128 | 128 | 0 | 82.88 | 60.728 | 255.438 | 359.966 | 81.307 | 7.101 |

All timing comes from perf_counter, never timeout settings.
Global serialization means increased concurrency can increase queue wait; this is not proof of a PostgreSQL bottleneck.
128 requests/profile and warm local small data support basic comparison only; P95/P99 are not stable production guarantees.
No live API, no measured Token usage. Driver/API serialization overhead outside AgentService is excluded.
Three controlled EXPLAIN ANALYZE/BUFFERS JSON plans are saved separately; no user EXPLAIN bypass is exposed.
