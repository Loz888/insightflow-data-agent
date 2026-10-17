"""Actual loopback HTTP + PostgreSQL benchmark; no paid model or vendor requests."""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import math
from pathlib import Path
from uuid import uuid4
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "2026年9月订单数是多少？",
    "2026年9月华东订单数是多少？",
    "2026年9月营收是多少？",
    "2026年9月退款率是多少？",
]


def serve(version, port):
    import uvicorn

    d = dotenv_values(ROOT / ".env")
    if version == "v1":
        from insightflow.api.app import create_app
        from insightflow.config import Settings

        app = create_app(Settings(database_url=d["INSIGHTFLOW_TEST_DATABASE_URL"]))
    else:
        from insightflow.v2.api import create_app
        from insightflow.v2.config import V2Settings

        app = create_app(
            V2Settings(
                runtime_url=d["INSIGHTFLOW_V2_TEST_RUNTIME_URL"],
                reader_url=d["INSIGHTFLOW_TEST_DATABASE_URL"],
                auth_tokens={"synthetic-loopback-benchmark-token": "benchmark"},
            )
        )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)


async def profile(version, port, count=32):
    records = []
    profiles = []
    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}", timeout=30, limits=httpx.Limits(max_connections=32)
    ) as c:
        for _ in range(100):
            try:
                if (await c.get("/health")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("HTTP server did not start")

        async def one(i, gate):
            async with gate:
                sid = uuid4().hex
                request = {"session_id": sid, "question": QUESTIONS[i % len(QUESTIONS)]}
                if version == "v2":
                    request["idempotency_key"] = uuid4().hex
                started = time.perf_counter()
                res = await c.post(
                    "/chat" if version == "v1" else "/v2/chat",
                    json=request,
                    headers={"Authorization": "Bearer synthetic-loopback-benchmark-token"},
                )
                data = res.json()
                ok = res.status_code == 200 and (
                    not data.get("error")
                    if version == "v1"
                    else data.get("status") == "succeeded"
                    and data.get("result", {}).get("disposition") == "answer"
                )
                record = {
                    "id": sid,
                    "version": version,
                    "status_code": res.status_code,
                    "success": ok,
                    "error": data.get("error") if version == "v1" else data.get("error_code"),
                    "duration_ms": (time.perf_counter() - started) * 1000,
                }
                records.append(record)
                return record

        # Warmup is reported separately and excluded from measured profiles.
        await one(0, asyncio.Semaphore(1))
        records.clear()
        for concurrency in (1, 2, 4, 8):
            gate = asyncio.Semaphore(concurrency)
            started = time.perf_counter()
            chunk = await asyncio.gather(*(one(i, gate) for i in range(count)))
            duration = time.perf_counter() - started
            times = sorted(x["duration_ms"] for x in chunk)
            profiles.append(
                {
                    "concurrency": concurrency,
                    "requests": count,
                    "successes": sum(x["success"] for x in chunk),
                    "throughput_rps": count / duration,
                    "p50_ms": times[math.ceil(count * 0.5) - 1],
                    "p95_ms": times[math.ceil(count * 0.95) - 1],
                    "p99_ms": times[math.ceil(count * 0.99) - 1],
                    "warm": "one-request prewarm; shared local PostgreSQL buffers",
                }
            )
    return {"version": version, "profiles": profiles, "runs": records}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", choices=["v1", "v2"])
    parser.add_argument("--port", type=int, default=18521)
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.serve:
        return serve(args.serve, args.port)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for version, port in [("v1", 18521), ("v2", 18522)]:
        env = dict(os.environ)
        env.pop("DEEPSEEK_API_KEY", None)
        env["INSIGHTFLOW_ENABLE_LIVE"] = "false"
        env["INSIGHTFLOW_ENABLE_PAID_EVAL"] = "0"
        env["INSIGHTFLOW_V2_MODE"] = "mock"
        env["INSIGHTFLOW_V2_LIVE_ENABLED"] = "false"
        proc = subprocess.Popen(
            [sys.executable, __file__, "--serve", version, "--port", str(port)],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        try:
            result = asyncio.run(profile(version, port))
            results.append(result)
        finally:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    # Hardware helper APIs differ across versions; keep metadata explicit and anonymous.
    report = {
        "entry": "actual loopback HTTP; same four question mix, real PostgreSQL, Mock models",
        "requests_per_version": 128,
        "results": results,
        "environment": {
            "cpu_count": os.cpu_count(),
            "python": sys.version.split()[0],
            "postgres": "16",
            "data_version": "v1-seed20261020",
            "orders": 500,
        },
        "limitations": [
            "Single local process per version; no paid model throughput.",
            "V2 includes durable runtime transactions; overhead is measured, not hidden.",
            "Warm data, small sample; no production P95/SLA claim.",
        ],
    }
    (out / "runs.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps([{k: v for k, v in item.items() if k != "runs"} for item in results], ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
