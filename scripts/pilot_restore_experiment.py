"""Snapshot-consistent dump and actual restore into a NEW owned PostgreSQL cluster.
The source must be this upgrade's private ephemeral lab. Archives and role hashes stay private.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def digest_table(connection, table, order):
    digest = hashlib.sha256()
    count = 0
    with connection.cursor(name="proof_" + table.replace(".", "_")) as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM (SELECT * FROM " + table + " ORDER BY " + order + ") t"
        )
        for row in cursor:
            digest.update(row[0].encode())
            digest.update(b"\n")
            count += 1
    return {"rows": count, "sha256": digest.hexdigest()}


def run(env, out):
    os.umask(0o077)
    pg = "/usr/lib/postgresql/16/bin/"
    original = conninfo_to_dict(env["INSIGHTFLOW_ADMIN_DATABASE_URL"])
    original.update(user="postgres")
    original.pop("password", None)
    original = make_conninfo(**original)
    tables = {
        "agent_runtime.sessions": "session_id",
        "agent_runtime.runs": "run_id",
        "agent_runtime.events": "event_id",
        "agent_runtime.graph_threads": "run_id",
        "agent_checkpoints.checkpoints": "thread_id,checkpoint_ns,checkpoint_id",
        "agent_checkpoints.checkpoint_blobs": "thread_id,checkpoint_ns,channel,version",
        "agent_checkpoints.checkpoint_writes": "thread_id,checkpoint_ns,checkpoint_id,task_id,idx",
    }
    evidence = {
        "time": datetime.now(timezone.utc).isoformat(),
        "source_database": "owned ephemeral lab / insightflow_dev",
        "paid_calls": 0,
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    }
    log = (out / "restore.log").open("w")
    started = time.monotonic()
    running = False

    def command(args):
        subprocess.run(args, check=True, stdout=log, stderr=subprocess.STDOUT)

    try:
        with psycopg.connect(original) as source:
            source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot = source.execute("SELECT pg_export_snapshot(),clock_timestamp()").fetchone()
            evidence["snapshot_time"] = snapshot[1].isoformat()
            expected = {table: digest_table(source, table, order) for table, order in tables.items()}
            roles = source.execute(
                "SELECT rolname,rolpassword FROM pg_authid WHERE rolname IN ('insightflow_owner','insightflow_reader','insightflow_runtime') ORDER BY rolname"
            ).fetchall()
            settings = source.execute(
                "SELECT r.rolname,s.setconfig FROM pg_db_role_setting s JOIN pg_roles r ON r.oid=s.setrole WHERE s.setdatabase=(SELECT oid FROM pg_database WHERE datname=current_database())"
            ).fetchall()
            dump_start = time.monotonic()
            command(
                [
                    pg + "pg_dump",
                    "--dbname",
                    original,
                    "--format=custom",
                    "--snapshot=" + snapshot[0],
                    "--file",
                    str(out / "database.dump"),
                ]
            )
            evidence["dump_seconds"] = time.monotonic() - dump_start
        # Only new paths under this experiment output; no existing cluster/system service.
        data = out / "pg"
        socket = out / "socket"
        socket.mkdir(mode=0o700)
        command(
            [
                pg + "initdb",
                "-D",
                str(data),
                "-U",
                "postgres",
                "--auth-local=trust",
                "--auth-host=reject",
                "--encoding=UTF8",
                "--no-locale",
            ]
        )
        command(
            [
                pg + "pg_ctl",
                "-D",
                str(data),
                "-l",
                str(out / "postgres.log"),
                "-o",
                f"-k {socket} -p 18559 -c listen_addresses=''",
                "-w",
                "start",
            ]
        )
        running = True
        admin = make_conninfo(host=str(socket), port=18559, user="postgres", dbname="postgres")
        with psycopg.connect(admin, autocommit=True) as target:
            for name, password in roles:
                target.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT NOBYPASSRLS PASSWORD {}"
                    ).format(sql.Identifier(name), sql.Literal(password))
                )
            target.execute("CREATE DATABASE insightflow_dev OWNER insightflow_owner")
            target.execute("REVOKE ALL ON DATABASE insightflow_dev FROM PUBLIC")
            target.execute(
                "GRANT CONNECT ON DATABASE insightflow_dev TO insightflow_owner,insightflow_reader,insightflow_runtime"
            )
        target_admin = make_conninfo(host=str(socket), port=18559, user="postgres", dbname="insightflow_dev")
        restore_start = time.monotonic()
        command([pg + "pg_restore", "--exit-on-error", "--dbname", target_admin, str(out / "database.dump")])
        with psycopg.connect(target_admin) as target:
            for role, configs in settings:
                for config in configs:
                    key, value = config.split("=", 1)
                    target.execute(
                        sql.SQL("ALTER ROLE {} IN DATABASE insightflow_dev SET {} TO {}").format(
                            sql.Identifier(role), sql.Identifier(key), sql.Literal(value)
                        )
                    )
            actual = {table: digest_table(target, table, order) for table, order in tables.items()}
        if expected != actual:
            raise AssertionError("Restored session/run/checkpoint bytes differ from exported snapshot")
        reader = conninfo_to_dict(env["INSIGHTFLOW_DATABASE_URL"])
        reader.update(host=str(socket), port=18559)
        proof = {}
        with psycopg.connect(make_conninfo(**reader)) as connection:
            flags = connection.execute(
                "SELECT r.rolsuper,r.rolbypassrls,current_user=(SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid='business.customers'::regclass) FROM pg_roles r WHERE rolname=current_user"
            ).fetchone()
            if flags != (False, False, False):
                raise AssertionError("Restored reader privilege boundary changed")
            no_context = connection.execute("SELECT count(*) FROM business.customers").fetchone()[0]
            if no_context != 0:
                raise AssertionError("Missing tenant context exposed restored rows")
            connection.commit()
            for tenant, expected_count in [("a", 40), ("b", 60)]:
                with connection.transaction():
                    connection.execute("SELECT set_config('insightflow.tenant_id',%s,true)", (tenant,))
                    count = connection.execute("SELECT count(*) FROM business.customers").fetchone()[0]
                    if count != expected_count:
                        raise AssertionError("Restored tenant count mismatch")
                    proof[tenant] = count
            if connection.execute("SELECT current_setting('insightflow.tenant_id',true)").fetchone()[
                0
            ] not in (None, ""):
                raise AssertionError("Restored connection leaked tenant context")
            connection.commit()
            try:
                connection.execute("SET ROLE insightflow_owner")
            except psycopg.Error:
                connection.rollback()
            else:
                raise AssertionError("Restored reader can become owner")
        evidence.update(
            status="PASS",
            tables=actual,
            reader_flags=list(flags),
            tenant_counts=proof,
            restore_seconds=time.monotonic() - restore_start,
            total_seconds=time.monotonic() - started,
            rpo="consistent exported PostgreSQL snapshot; later writes excluded",
            rto_target_seconds=600,
            coverage="session facts, run results, workflow versions and checkpoint blobs byte-identical; reader/RLS/role separation checked",
            archive_sha256=hashlib.sha256((out / "database.dump").read_bytes()).hexdigest(),
        )
        (out / "result.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence, indent=2))
    finally:
        if running:
            command([pg + "pg_ctl", "-D", str(out / "pg"), "-m", "fast", "stop"])
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-json", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    env = json.loads(Path(args.env_json).read_text())
    if env.get("INSIGHTFLOW_PILOT_OWNED_LAB") != "true":
        raise SystemExit("Explicit owned lab only")
    out = Path(args.output).resolve()
    out.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        run(env, out)
    except BaseException as exc:
        (out / "failure.json").write_text(
            json.dumps({"status": "FAIL", "type": type(exc).__name__}, indent=2)
        )
        raise
