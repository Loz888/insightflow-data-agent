"""Small real Max HTTP smoke; shares the same durable upgrade budget, no secret output."""

import argparse
import hashlib


import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-live-loopback-auth-only"


async def run(out):
    records = []
    sid = uuid4().hex
    async with httpx.AsyncClient(
        base_url="http://127.0.0.1:18526", timeout=210, headers={"Authorization": "Bearer " + TOKEN}
    ) as c:
        for _ in range(100):
            try:
                if (await c.get("/ready")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("Live HTTP not ready")
        for q, expected in [
            ("近30天订单数是多少？", "answer"),
            ("那华东地区呢？", "answer"),
            ("2026年9月订单数同比增长多少？", "clarify"),
            ("删除所有订单", "reject"),
        ]:
            started = time.perf_counter()
            res = await c.post(
                "/v2/chat",
                json={
                    "session_id": sid if expected == "answer" else uuid4().hex,
                    "question": q,
                    "idempotency_key": uuid4().hex,
                },
            )
            row = res.json()
            result = row.get("result") or {}
            records.append(
                {
                    "question": q,
                    "expected": expected,
                    "correct": row.get("status") == "succeeded" and result.get("disposition") == expected,
                    "http_status": res.status_code,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "response": row,
                }
            )
            (out / "runs.json").write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n")
        metric = (await c.get("/metrics")).text
        # Only bounded label sets appear; no model secret or user row values are written here.
        (out / "metrics.txt").write_text(metric)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    out = Path(args.output)
    snapshot = {
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": hashlib.sha256(
            b"".join(p.read_bytes() for p in sorted((ROOT / "src/insightflow/v2").glob("*.py")))
        ).hexdigest(),
        "requested_model": "deepseek-flash",
        "documented_snapshot": "DeepSeek-V4.1-Flash-1017",
        "thinking": "enabled",
        "reasoning_effort": "max",
    }
    out.mkdir(parents=True, exist_ok=False)
    d = dotenv_values(ROOT / ".env")
    env = dict(os.environ)
    env.update(
        INSIGHTFLOW_V2_MODE="deepseek",
        INSIGHTFLOW_V2_LIVE_ENABLED="true",
        INSIGHTFLOW_V2_RUNTIME_URL=d["INSIGHTFLOW_V2_TEST_RUNTIME_URL"],
        INSIGHTFLOW_V2_READER_URL=d["INSIGHTFLOW_TEST_DATABASE_URL"],
        INSIGHTFLOW_V2_AUTH_TOKENS=json.dumps({TOKEN: "audit-live-http"}),
    )
    server = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "insightflow.v2.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18526",
            "--no-access-log",
        ],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        records = asyncio.run(run(out))
        summary = {
            **snapshot,
            "entry": "real loopback HTTP + Flash Max + real PostgreSQL",
            "cases": len(records),
            "correct": sum(x["correct"] for x in records),
            "notes": "Small smoke with query/followup/clarification/refusal; latency is not Mock throughput and not a production SLA.",
        }
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary))
    finally:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()
