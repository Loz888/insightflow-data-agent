import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import math
import os
import platform
import time
from uuid import uuid4
from pathlib import Path
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.database.connection import checked_connection
from insightflow.evaluation.runner import ROOT
from insightflow.evaluation.scorer import equivalent


def percentile(values, p):
    if not values:
        raise ValueError("No latency samples")
    return sorted(values)[math.ceil(len(values) * p) - 1]


def run_profile(dsn, cases, concurrency, requests=128):
    if concurrency not in (1, 2, 4, 8) or not 1 <= requests <= 128:
        raise ValueError("Controlled profile size required")
    service = AgentService(Settings(database_url=SecretStr(dsn), mode="mock"))

    def run(index):
        case = cases[index % len(cases)]
        external_id = uuid4().hex
        started = time.perf_counter()
        try:
            state = service.run(case["question"], "perf-" + external_id)
            success = state.get("error") is None and equivalent(
                state.get("query_result", {}), case["expected_result"], case.get("ordered", False)
            )
            return {
                "run_id": state["request_id"],
                "case_id": case["case_id"],
                "concurrency": concurrency,
                "succeeded": bool(success),
                "duration_ms": (time.perf_counter() - started) * 1000,
                "total_duration_ms": state["total_duration_ms"],
                "timings": state["timings"],
                "node_events": state["node_events"],
                "model_calls": state["model_calls"],
                "token_usage_known": state["usage"]["token_usage_known"],
                "input_tokens": state["usage"]["input_tokens"],
                "output_tokens": state["usage"]["output_tokens"],
                "error_kind": state["error"]["kind"]
                if state.get("error")
                else (None if success else "RESULT_MISMATCH"),
            }
        except Exception as exc:
            from insightflow.database.errors import AgentError

            return {
                "run_id": external_id,
                "case_id": case["case_id"],
                "concurrency": concurrency,
                "succeeded": False,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "error_kind": exc.kind.value if isinstance(exc, AgentError) else "INTERNAL_ERROR",
                "timings": {},
                "node_events": [],
                "token_usage_known": False,
                "input_tokens": None,
                "output_tokens": None,
                "model_calls": None,
            }

    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as workers:
            records = list(workers.map(run, range(requests)))
    finally:
        service.close()
    seconds = time.perf_counter() - started
    durations = [r["duration_ms"] for r in records]
    succeeded = sum(r["succeeded"] for r in records)
    summary = {
        "concurrency": concurrency,
        "requests": requests,
        "completed": len(records),
        "succeeded": succeeded,
        "failed": len(records) - succeeded,
        "elapsed_seconds": seconds,
        "throughput_requests_per_second": len(records) / seconds,
        "p50_ms": percentile(durations, 0.5),
        "p95_ms": percentile(durations, 0.95),
        "p99_ms": percentile(durations, 0.99),
        "error_distribution": dict(Counter(r["error_kind"] for r in records if r["error_kind"])),
        "average_queue_wait_ms": sum(r["timings"].get("queue_wait_ms", 0) for r in records) / len(records),
        "average_sql_ms": sum(r["timings"].get("sql_duration_ms", 0) for r in records) / len(records),
        "token_usage_known_cases": sum(r["token_usage_known"] for r in records),
        "input_tokens": None,
        "output_tokens": None,
    }
    return records, summary


def plans(dsn, validator):
    queries = {
        "single_filter": "SELECT id FROM business.orders WHERE status='paid' AND id<100",
        "join_group": "SELECT c.region,SUM(i.quantity*i.unit_price) FROM business.orders o JOIN business.customers c ON c.id=o.customer_id JOIN business.order_items i ON i.order_id=o.id WHERE o.status='paid' GROUP BY c.region",
        "time_aggregate": "SELECT COUNT(*) FROM business.orders WHERE ordered_at>='2026-09-01' AND ordered_at<'2026-10-01'",
    }
    results = {}
    with checked_connection(dsn, test_only=True) as conn:
        conn.execute("SET LOCAL statement_timeout='1500ms'")
        conn.execute("SET LOCAL lock_timeout='200ms'")
        for name, sql in queries.items():
            approved = validator.validate(sql)
            # Controlled diagnostic only: user-supplied EXPLAIN remains rejected.
            results[name] = {
                "sql": approved.sql,
                "plan": conn.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + approved.sql).fetchone()[0],
            }
    return results


def main():
    import logging

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--requests", type=int, default=128)
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    dsn = os.environ["INSIGHTFLOW_TEST_DATABASE_URL"]
    cases = [
        c
        for c in json.loads((ROOT / "evaldata/questions.json").read_text())
        if c["case_id"] in ("q01", "q04", "q12", "q14", "q15", "q21", "q23", "q25")
    ]
    records = []
    summary = {}
    for level in (1, 2, 4, 8):
        rows, profile = run_profile(dsn, cases, level, args.requests)
        records.extend(rows)
        summary[str(level)] = profile
    service = AgentService(Settings(database_url=SecretStr(dsn)))
    try:
        execution_plans = plans(dsn, service.executor.validator)
    finally:
        service.close()
    with checked_connection(dsn, test_only=True) as conn:
        postgres = conn.execute("SHOW server_version").fetchone()[0]
    cpu = next(
        (
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
        "unknown",
    )
    memory = next(
        (
            line.split()[1]
            for line in Path("/proc/meminfo").read_text().splitlines()
            if line.startswith("MemTotal")
        ),
        "unknown",
    )
    metadata = {
        "platform": "Linux/WSL",
        "python": platform.python_version(),
        "postgresql": postgres,
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "visible_memory_kib": memory,
        "dataset": {"customers": 100, "products": 30, "orders": 500, "order_items": 1001, "refunds": 165},
        "model": "mock",
        "entrypoint": "AgentService.run (not HTTP throughput)",
        "warm_cache": True,
        "percentile": "nearest rank ceil(n*p)-1",
        "session_policy": "global serialized lock",
        "snapshot": "fixed synthetic seed 20261020",
    }
    (out / "runs.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (out / "summary.json").write_text(
        json.dumps({"environment": metadata, "profiles": summary}, ensure_ascii=False, indent=2) + "\n"
    )
    (out / "plans.json").write_text(json.dumps(execution_plans, ensure_ascii=False, indent=2) + "\n")
    lines = [
        "# Performance experiment",
        "",
        json.dumps(metadata, ensure_ascii=False),
        "",
        "| Concurrency | Requests | Completed | Succeeded | Failed | req/s | P50 ms | P95 ms | P99 ms | Queue avg ms | SQL avg ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for level, s in summary.items():
        lines.append(
            f"| {level} | {s['requests']} | {s['completed']} | {s['succeeded']} | {s['failed']} | {s['throughput_requests_per_second']:.2f} | {s['p50_ms']:.3f} | {s['p95_ms']:.3f} | {s['p99_ms']:.3f} | {s['average_queue_wait_ms']:.3f} | {s['average_sql_ms']:.3f} |"
        )
    lines += [
        "",
        "All timing comes from perf_counter, never timeout settings.",
        "Global serialization means increased concurrency can increase queue wait; this is not proof of a PostgreSQL bottleneck.",
        "128 requests/profile and warm local small data support basic comparison only; P95/P99 are not stable production guarantees.",
        "No live API, no measured Token usage. Driver/API serialization overhead outside AgentService is excluded.",
        "Three controlled EXPLAIN ANALYZE/BUFFERS JSON plans are saved separately; no user EXPLAIN bypass is exposed.",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary))
    return 1 if any(p["failed"] for p in summary.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
