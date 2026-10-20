import argparse
from pathlib import Path
import os
import subprocess
import json
import shutil
import secrets
import sys
import time

os.umask(0o077)

parser = argparse.ArgumentParser(
    description="Verify in a NEW local PostgreSQL cluster and new Python venv; never modify existing cluster"
)
parser.add_argument("--output", required=True)
args = parser.parse_args()
r = Path(__file__).resolve().parents[1]
audit = Path(args.output).resolve()
audit.mkdir(parents=True, exist_ok=False)
fresh = audit / "source"
fresh.mkdir()
pg = audit / "pg"
port = "18539"
log = (audit / "verification.txt").open("w")
files = (
    subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=r)
    .decode()
    .split("\0")
)
for n in filter(None, files):
    p = r / n
    if p.is_file():
        q = fresh / n
        q.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, q)
password = secrets.token_urlsafe(32)
pw = audit / "admin-password"
pw.write_text(password)
pw.chmod(0o600)


def run(args, cwd=fresh, env=None):
    result = subprocess.run(args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError("Step failed: " + str(args[0]) + " " + str(args[1:3]))


started = False
try:
    run(
        [
            "/usr/lib/postgresql/16/bin/initdb",
            "-D",
            str(pg),
            "--username=postgres",
            "--auth-host=scram-sha-256",
            "--auth-local=trust",
            "--pwfile=" + str(pw),
        ]
    )
    run(
        [
            "/usr/lib/postgresql/16/bin/pg_ctl",
            "-D",
            str(pg),
            "-l",
            str(audit / "postgres.txt"),
            "-o",
            "-p " + port + " -h 127.0.0.1 -k " + str(audit),
            "start",
        ]
    )
    started = True
    run([sys.executable, "-m", "venv", str(fresh / ".venv")])
    python = str(fresh / ".venv/bin/python")
    run([python, "-m", "pip", "install", "-r", "requirements.lock"])
    run([python, "-m", "pip", "install", "--no-deps", "-e", "."])
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("INSIGHTFLOW_", "DEEPSEEK_")):
            env.pop(key)
    from psycopg.conninfo import make_conninfo

    owner_pw = secrets.token_urlsafe(32)
    reader_pw = secrets.token_urlsafe(32)
    runtime_pw = secrets.token_urlsafe(32)
    base = {"host": "127.0.0.1", "port": port, "sslmode": "disable"}
    env.update(
        GITHUB_ACTIONS="true",
        GITHUB_ENV=str(audit / "github-env"),
        INSIGHTFLOW_CI_ADMIN_DATABASE_URL=make_conninfo(
            **base, dbname="postgres", user="postgres", password=password
        ),
        INSIGHTFLOW_CI_OWNER_PASSWORD=owner_pw,
        INSIGHTFLOW_CI_READER_PASSWORD=reader_pw,
        INSIGHTFLOW_CI_RUNTIME_PASSWORD=runtime_pw,
        INSIGHTFLOW_MODE="mock",
        INSIGHTFLOW_ENABLE_PAID_EVAL="0",
        INSIGHTFLOW_ENABLE_LIVE="false",
        LANGSMITH_TRACING="false",
    )
    for prefix, db in [("", "insightflow_dev"), ("TEST_", "insightflow_test")]:
        env["INSIGHTFLOW_" + prefix + "ADMIN_DATABASE_URL"] = make_conninfo(
            **base, dbname=db, user="insightflow_owner", password=owner_pw
        )
        env["INSIGHTFLOW_" + prefix + "DATABASE_URL"] = make_conninfo(
            **base, dbname=db, user="insightflow_reader", password=reader_pw
        )
    run([python, "scripts/ci_init.py"], env=env)
    run([python, "scripts/seed_data.py", "--initialize"], env=env)
    run([python, "scripts/ci_v2.py"], env=env)
    for line in (audit / "github-env").read_text().splitlines():
        k, v = line.split("=", 1)
        env[k] = v
    # Exercise the same preflight, tests, demo and strict original evaluation as CI.
    run([python, "scripts/accept.py", "--output", str(audit / "acceptance")], env=env)
    shutil.copy2(audit / "acceptance/tests.json", audit / "tests.json")
    # A second additive migration pass must preserve all business counts and runtime records.
    run([python, "scripts/migrate_v2.py", "--seed-empty"], env=env)
    # Real HTTP, actual fresh cluster, no model credential in process environment.
    server = subprocess.Popen(
        [
            python,
            "-m",
            "uvicorn",
            "insightflow.v2.api:app",
            "--host",
            "127.0.0.1",
            "--port",
            "18538",
            "--no-access-log",
        ],
        cwd=fresh,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        import httpx

        with httpx.Client(base_url="http://127.0.0.1:18538", timeout=15, trust_env=False) as c:
            for _ in range(100):
                try:
                    if c.get("/ready").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.1)
            else:
                raise RuntimeError("Fresh HTTP readiness failed")
            token = json.loads(env["INSIGHTFLOW_V2_AUTH_TOKENS"])
            token = next(iter(token))
            response = c.post(
                "/v2/chat",
                headers={"Authorization": "Bearer " + token},
                json={
                    "session_id": "fresh-http",
                    "question": "2026年9月排除华东订单数是多少？",
                    "idempotency_key": "fresh-http-001",
                },
            )
            data = response.json()
            if (
                response.status_code != 200
                or data.get("status") != "succeeded"
                or data.get("result", {}).get("disposition") != "answer"
            ):
                raise RuntimeError("Fresh HTTP E2E failed")
            (audit / "http.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    finally:
        server.terminate()
        server.wait(timeout=10)
    evidence = {
        "status": "PASS",
        "environment": "new Python venv + newly initialized PostgreSQL16 cluster; fresh 4 databases, no original cluster changed",
        "tests": json.loads((audit / "tests.json").read_text()),
        "http": "PASS",
        "migration_replay": "PASS",
        "docker": "BLOCKED_NO_ENGINE",
        "paid_model": "NOT_RUN_IN_FRESH_CI",
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=r, text=True).strip(),
    }
    (audit / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (r / "reports/pilot/fresh-environment.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence))
except Exception as exc:
    print("FRESH_FAILURE", type(exc).__name__, str(exc))
    raise
finally:
    if started:
        subprocess.run(
            ["/usr/lib/postgresql/16/bin/pg_ctl", "-D", str(pg), "-m", "fast", "stop"],
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    log.close()
