"""Only for a fresh ephemeral GitHub Actions PostgreSQL service."""

import os
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("CI bootstrap is restricted to the explicitly configured ephemeral runner.")
dsn = os.environ["INSIGHTFLOW_CI_ADMIN_DATABASE_URL"]
params = conninfo_to_dict(dsn)
if (
    params.get("host") != "127.0.0.1"
    or params.get("dbname") != "postgres"
    or params.get("user") != "postgres"
):
    raise SystemExit("Unexpected CI administrator endpoint.")
with psycopg.connect(dsn, autocommit=True, connect_timeout=3) as conn:
    if conn.execute(
        "SELECT 1 FROM pg_roles WHERE rolname IN ('insightflow_owner','insightflow_reader')"
    ).fetchone():
        raise SystemExit("Refusing to replace existing roles.")
    if conn.execute(
        "SELECT 1 FROM pg_database WHERE datname IN ('insightflow_dev','insightflow_test')"
    ).fetchone():
        raise SystemExit("Refusing to replace existing databases.")
    for role, variable in [
        ("insightflow_owner", "INSIGHTFLOW_CI_OWNER_PASSWORD"),
        ("insightflow_reader", "INSIGHTFLOW_CI_READER_PASSWORD"),
        ("insightflow_runtime", "INSIGHTFLOW_CI_RUNTIME_PASSWORD"),
    ]:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOINHERIT PASSWORD {}"
            ).format(sql.Identifier(role), sql.Literal(os.environ[variable]))
        )
    for name in ("insightflow_dev", "insightflow_test", "insightflow_v2_seed101", "insightflow_v2_seed202"):
        ident = sql.Identifier(name)
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER insightflow_owner").format(ident))
        conn.execute(sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(ident))
        conn.execute(
            sql.SQL(
                "GRANT CONNECT ON DATABASE {} TO insightflow_owner,insightflow_reader,insightflow_runtime"
            ).format(ident)
        )
        conn.execute(
            sql.SQL(
                "ALTER ROLE insightflow_reader IN DATABASE {} SET default_transaction_read_only=on"
            ).format(ident)
        )
        conn.execute(
            sql.SQL("ALTER ROLE insightflow_reader IN DATABASE {} SET statement_timeout='1500ms'").format(
                ident
            )
        )
        conn.execute(
            sql.SQL(
                "ALTER ROLE insightflow_reader IN DATABASE {} SET search_path=pg_catalog,business"
            ).format(ident)
        )
print("Created only ephemeral InsightFlow databases and separate non-superuser roles.")
