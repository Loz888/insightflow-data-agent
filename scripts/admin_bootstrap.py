"""Explicit administrator-only bootstrap for NEW isolated demo databases."""

import os
import pwd
import secrets
import subprocess
from pathlib import Path
from psycopg import sql
from psycopg.conninfo import make_conninfo

root = Path(__file__).resolve().parents[1]
if os.geteuid() != 0:
    raise SystemExit("Run explicitly via an administrator; query service must never run as root.")
if (root / ".env").exists():
    raise SystemExit("Existing .env retained: inspect existing setup; never rotate credentials implicitly.")
reader_password, owner_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)


def admin(statement):
    return subprocess.run(
        [
            "/usr/sbin/runuser",
            "-u",
            "postgres",
            "--",
            "/usr/bin/psql",
            "-X",
            "-d",
            "postgres",
            "-v",
            "ON_ERROR_STOP=1",
            "-Atq",
        ],
        input=statement,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


for name in ("insightflow_reader", "insightflow_owner"):
    if admin(sql.SQL("SELECT 1 FROM pg_roles WHERE rolname={}").format(sql.Literal(name)).as_string()):
        raise SystemExit("InsightFlow role already exists; manual audit required before initialization.")
for name in ("insightflow_dev", "insightflow_test"):
    if admin(sql.SQL("SELECT 1 FROM pg_database WHERE datname={}").format(sql.Literal(name)).as_string()):
        raise SystemExit("InsightFlow database already exists; refusing to change ownership or reset.")
for role, password in [("insightflow_owner", owner_password), ("insightflow_reader", reader_password)]:
    admin(
        sql.SQL(
            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}"
        )
        .format(sql.Identifier(role), sql.Literal(password))
        .as_string()
    )
for name in ("insightflow_dev", "insightflow_test"):
    admin(sql.SQL("CREATE DATABASE {} OWNER insightflow_owner").format(sql.Identifier(name)).as_string())
    admin(
        sql.SQL(
            "REVOKE ALL ON DATABASE {} FROM PUBLIC; GRANT CONNECT ON DATABASE {} TO insightflow_owner, insightflow_reader"
        )
        .format(sql.Identifier(name), sql.Identifier(name))
        .as_string()
    )
    admin(
        sql.SQL("ALTER ROLE insightflow_reader IN DATABASE {} SET default_transaction_read_only = on")
        .format(sql.Identifier(name))
        .as_string()
    )
    admin(
        sql.SQL("ALTER ROLE insightflow_reader IN DATABASE {} SET statement_timeout = '1500ms'")
        .format(sql.Identifier(name))
        .as_string()
    )
    admin(
        sql.SQL("ALTER ROLE insightflow_reader IN DATABASE {} SET search_path = business,pg_catalog")
        .format(sql.Identifier(name))
        .as_string()
    )
values = {}
for prefix, database in [("", "insightflow_dev"), ("TEST_", "insightflow_test")]:
    for admin_role, role, password in [
        (False, "insightflow_reader", reader_password),
        (True, "insightflow_owner", owner_password),
    ]:
        key = "INSIGHTFLOW_" + prefix + ("ADMIN_" if admin_role else "") + "DATABASE_URL"
        values[key] = make_conninfo(
            host="127.0.0.1", dbname=database, user=role, password=password, sslmode="disable"
        )
path = root / ".env"
fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as f:
    for k, v in values.items():
        f.write(k + "=" + repr(v) + "\n")
uid = root.stat().st_uid
info = pwd.getpwuid(uid)
os.chown(path, uid, info.pw_gid)
print("Created only insightflow_dev/test with separate owner and reader; .env is local mode 0600.")
