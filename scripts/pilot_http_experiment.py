"""Owned loopback two-process fault/performance/30-minute experiment, strictly Mock.
Input environment is a private JSON file produced by the fresh lab; never read project .env.
"""

import argparse
import asyncio
import hashlib
import json
import math
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import httpx
import psycopg
from insightflow.v2.identity import token_hash


async def experiment(env, root, out, seconds, standard, soak_only):
    processes = []
    logs = []
    ports = [18541, 18542]
    token = "synthetic-http-lab-" + secrets.token_hex(24)
    owner = env["INSIGHTFLOW_ADMIN_DATABASE_URL"]
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    p = conninfo_to_dict(env["INSIGHTFLOW_V2_TEST_RUNTIME_URL"])
    p["dbname"] = "insightflow_dev"
    runtime = make_conninfo(**p)
    env = {
        **env,
        "PYTHONPATH": str(out / "source/src"),
        "INSIGHTFLOW_V2_RUNTIME_URL": runtime,
        "INSIGHTFLOW_V2_READER_URL": env["INSIGHTFLOW_DATABASE_URL"],
        "INSIGHTFLOW_V2_PROFILE": "internal-pilot",
        "INSIGHTFLOW_V2_PILOT_TENANTS": '["a","b"]',
        "INSIGHTFLOW_V2_AUTH_TOKENS": "{}",
        "INSIGHTFLOW_V2_MODE": "mock",
        "INSIGHTFLOW_V2_LIVE_ENABLED": "false",
        "INSIGHTFLOW_V2_ACTIVE_LIMIT": "32",
    }
    env.pop("DEEPSEEK_API_KEY", None)
    source = out / "source"
    source.mkdir()
    shutil.copytree(root / "src", source / "src", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(root / "scripts", source / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    manifest = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source.rglob("*.py")
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    with psycopg.connect(owner) as c:
        c.execute(
            "INSERT INTO agent_runtime.api_tokens(token_hash,principal,tenant,datasource,expires_at) VALUES(%s,'http-experiment','a','business',clock_timestamp()+interval '4 hours')",
            (token_hash(token),),
        )
    headers = {"Authorization": "Bearer " + token}

    def launch(i, pause=False):
        childenv = {**env, "PILOT_HTTP_PORT": str(ports[i])}
        if pause:
            childenv["PILOT_PAUSE_MARKER"] = str(out / "paused")
        log = (out / ("server-" + str(i) + "-" + uuid4().hex[:6] + ".log")).open("w")
        logs.append(log)
        child = subprocess.Popen(
            [sys.executable, str(source / "scripts/pilot_http_server.py")],
            env=childenv,
            cwd=source,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        processes.append(child)
        return child

    async with httpx.AsyncClient(headers=headers, timeout=30, trust_env=False) as client:

        async def ready(i):
            for _ in range(200):
                try:
                    res = await client.get(f"http://127.0.0.1:{ports[i]}/ready")
                    if res.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.05)
            raise RuntimeError("owned API readiness failed")

        async def post(i, sid, q="客户数是多少？", key=None, wait=True):
            started = time.perf_counter()
            res = await client.post(
                f"http://127.0.0.1:{ports[i]}/v2/" + ("chat" if wait else "runs"),
                json={"session_id": sid, "question": q, "idempotency_key": key or uuid4().hex},
            )
            return res, (time.perf_counter() - started) * 1000

        try:
            a = launch(0, True)
            await ready(0)
            sid = uuid4().hex
            res, _ = await post(0, sid, wait=False)
            assert res.status_code == 202, res.text
            rid = res.json()["run_id"]
            for _ in range(200):
                if (out / "paused").exists():
                    break
                await asyncio.sleep(0.02)
            assert (out / "paused").exists()
            os.kill(a.pid, signal.SIGKILL)
            a.wait(timeout=5)
            # Wait for actual expiry, never forge DB epochs/lease times.
            await asyncio.sleep(16)
            a = launch(0)
            b = launch(1)
            await ready(0)
            await ready(1)
            resumed = await client.post(f"http://127.0.0.1:{ports[1]}/v2/runs/{rid}/resume")
            assert resumed.status_code == 200, resumed.text
            for _ in range(400):
                row = (await client.get(f"http://127.0.0.1:{ports[0]}/v2/runs/{rid}")).json()
                if row["status"] in ["succeeded", "failed", "cancelled"]:
                    break
                await asyncio.sleep(0.025)
            assert row["status"] == "succeeded", row
            assert row["result"]["evidence"]["rows"] == [[40]], row
            session = (await client.get(f"http://127.0.0.1:{ports[1]}/v2/sessions/{sid}")).json()
            assert session["version"] == 1
            # Same request concurrent across both actual processes: one durable run/history.
            sid = uuid4().hex
            key = uuid4().hex
            replies = await asyncio.gather(post(0, sid, key=key), post(1, sid, key=key))
            assert all(x[0].status_code == 200 for x in replies)
            assert len({x[0].json()["run_id"] for x in replies}) == 1
            session = (await client.get(f"http://127.0.0.1:{ports[0]}/v2/sessions/{sid}")).json()
            assert session["version"] == 1
            faults = {
                "sigkill_mid_graph": "PASS",
                "actual_processes": 2,
                "resume_same_run": "PASS",
                "response_replay_history_once": "PASS",
                "paid_calls": 0,
            }
            (out / "faults.json").write_text(json.dumps(faults, indent=2))
            raw = (out / "requests.jsonl").open("w")
            samples = (out / "resources.jsonl").open("w")

            async def one(i, phase, concurrency, repeat):
                started = time.perf_counter()
                try:
                    res, ms = await post(i % 2, uuid4().hex)
                    row = res.json()
                    ok = (
                        res.status_code == 200
                        and row.get("status") == "succeeded"
                        and row.get("result", {}).get("evidence", {}).get("rows") == [[40]]
                    )
                    record = {
                        "phase": phase,
                        "concurrency": concurrency,
                        "repeat": repeat,
                        "http_status": res.status_code,
                        "status": row.get("status"),
                        "error": row.get("error_code"),
                        "correct": ok,
                        "latency_ms": ms,
                    }
                except (httpx.HTTPError, ValueError) as exc:
                    record = {
                        "phase": phase,
                        "concurrency": concurrency,
                        "repeat": repeat,
                        "http_status": 0,
                        "status": "client_error",
                        "error": type(exc).__name__,
                        "correct": False,
                        "latency_ms": (time.perf_counter() - started) * 1000,
                    }
                raw.write(json.dumps(record) + "\n")
                raw.flush()
                return record

            groups = []
            for concurrency in [] if soak_only else [1, 4, 8, 16, 32]:
                for repeat in range(3 if standard else 1):
                    limit = asyncio.Semaphore(concurrency)

                    async def limited(i):
                        async with limit:
                            return await one(i, "benchmark", concurrency, repeat)

                    started = time.perf_counter()
                    records = await asyncio.gather(*(limited(i) for i in range(1000 if standard else 100)))
                    elapsed = time.perf_counter() - started
                    lat = sorted(x["latency_ms"] for x in records)
                    groups.append(
                        {
                            "concurrency": concurrency,
                            "repeat": repeat,
                            "n": len(records),
                            "success": sum(x["correct"] for x in records),
                            "rps": len(records) / elapsed,
                            "p50": lat[math.ceil(0.50 * len(lat)) - 1],
                            "p95": lat[math.ceil(0.95 * len(lat)) - 1],
                            "p99": lat[math.ceil(0.99 * len(lat)) - 1],
                        }
                    )
                    raw.flush()
                    (out / "benchmark.json").write_text(json.dumps(groups, indent=2))
            started = time.monotonic()
            count = 0
            while time.monotonic() - started < seconds:
                await one(count, "soak", 1, 0)
                count += 1
                if count % 10 == 0:
                    rss = {}
                    for process in [a, b]:
                        status = Path(f"/proc/{process.pid}/status").read_text()
                        rss[str(process.pid)] = next(x for x in status.splitlines() if x.startswith("VmRSS:"))
                    with psycopg.connect(owner) as c:
                        data = c.execute(
                            "SELECT (SELECT count(*) FROM agent_runtime.runs),(SELECT count(*) FROM agent_checkpoints.checkpoints),pg_database_size(current_database()),(SELECT count(*) FROM pg_stat_activity WHERE datname=current_database())"
                        ).fetchone()
                    samples.write(
                        json.dumps(
                            {
                                "elapsed_seconds": time.monotonic() - started,
                                "rss": rss,
                                "run_rows": data[0],
                                "checkpoint_rows": data[1],
                                "database_bytes": data[2],
                                "connections": data[3],
                            }
                        )
                        + "\n"
                    )
                    samples.flush()
                    raw.flush()
                await asyncio.sleep(max(0, started + count - time.monotonic()))
            raw.close()
            samples.close()
            summary = {
                "status": "PASS",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "soak_seconds": time.monotonic() - started,
                "soak_requests": count,
                "standard": standard,
                "paid_calls": 0,
                "percentile": "nearest-rank",
                "load": "closed loop bounded clients; one request/sec target for soak",
                "trace_source": "immutable source copy manifest.json",
            }
            (out / "summary.json").write_text(json.dumps(summary, indent=2))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
            for log in logs:
                log.close()
            with psycopg.connect(owner) as c:
                c.execute(
                    "UPDATE agent_runtime.api_tokens SET revoked_at=clock_timestamp() WHERE token_hash=%s",
                    (token_hash(token),),
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seconds", type=int, default=1800)
    parser.add_argument("--standard", action="store_true")
    parser.add_argument("--soak-only", action="store_true")
    args = parser.parse_args()
    env = json.loads(Path(args.env_json).read_text())
    if env.get("INSIGHTFLOW_PILOT_OWNED_LAB") != "true":
        raise SystemExit("Owned lab required")
    out = Path(args.output)
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        asyncio.run(
            experiment(
                env, Path(__file__).resolve().parents[1], out, args.seconds, args.standard, args.soak_only
            )
        )
    except BaseException as exc:
        (out / "failure.json").write_text(
            json.dumps({"status": "FAIL", "type": type(exc).__name__}, indent=2)
        )
        raise
