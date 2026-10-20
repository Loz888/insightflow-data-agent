"""Additive, digest-tracked migrations; seed only by explicit --seed-empty on empty business data."""

import argparse
import hashlib
import os
from pathlib import Path
from dotenv import dotenv_values
from insightflow.database.connection import checked_connection
from seed_data import seed

ROOT = Path(__file__).resolve().parents[1]


def migrate(owner, seed_empty=False):
    from psycopg import sql

    c = checked_connection(owner, owner=True)
    locked = False
    try:
        # Session lock spans additive DDL AND the explicit empty-fixture seed phase.
        c.execute("SELECT pg_advisory_lock(61720261017)")
        c.commit()
        locked = True
        rls = c.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='business' AND t.relrowsecurity)"
        ).fetchone()[0]
        existing = [
            row[0]
            for row in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='business'").fetchall()
        ]
        empty = not rls
        if empty:
            for table in existing:
                if c.execute(
                    sql.SQL("SELECT EXISTS(SELECT 1 FROM business.{} LIMIT 1)").format(sql.Identifier(table))
                ).fetchone()[0]:
                    empty = False
                    break
        if c.execute("SELECT to_regclass('agent_runtime.runs')").fetchone()[0] is not None:
            if c.execute("SELECT EXISTS(SELECT 1 FROM agent_runtime.runs LIMIT 1)").fetchone()[0]:
                empty = False
        # RLS-filtered zero rows never authorise TRUNCATE/seed. Existing data in ANY
        # business table or previous agent records also forbids implicit reset.
        c.execute("CREATE SCHEMA IF NOT EXISTS agent_runtime")
        c.execute(
            "CREATE TABLE IF NOT EXISTS agent_runtime.schema_migrations(version text PRIMARY KEY,digest text NOT NULL,applied_at timestamptz NOT NULL DEFAULT clock_timestamp())"
        )
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            old = c.execute(
                "SELECT digest FROM agent_runtime.schema_migrations WHERE version=%s", (path.name,)
            ).fetchone()
            if old:
                if old[0] != digest:
                    raise ValueError("Applied migration changed: " + path.name)
                continue
            c.execute(path.read_text())
            c.execute(
                "INSERT INTO agent_runtime.schema_migrations(version,digest) VALUES(%s,%s)",
                (path.name, digest),
            )
        c.execute("GRANT USAGE ON SCHEMA agent_runtime TO insightflow_runtime")
        c.execute(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA agent_runtime TO insightflow_runtime"
        )
        c.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA agent_runtime TO insightflow_runtime")
        c.execute("REVOKE ALL ON agent_runtime.schema_migrations FROM insightflow_runtime")
        c.execute("REVOKE INSERT,UPDATE,DELETE ON agent_runtime.api_tokens FROM insightflow_runtime")
        c.commit()
        if seed_empty and empty:
            seed(owner)
    except BaseException:
        c.rollback()
        raise
    finally:
        if locked:
            c.execute("SELECT pg_advisory_unlock(61720261017)")
            c.commit()
        c.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-empty", action="store_true")
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    d = {**dotenv_values(ROOT / ".env"), **os.environ}
    names = (
        ("INSIGHTFLOW_TEST_ADMIN_DATABASE_URL",)
        if args.test_only
        else ("INSIGHTFLOW_ADMIN_DATABASE_URL", "INSIGHTFLOW_TEST_ADMIN_DATABASE_URL")
    )
    for name in names:
        if d.get(name):
            migrate(d[name], args.seed_empty)
    print("Versioned additive migrations applied; existing business rows retained.")


if __name__ == "__main__":
    main()
