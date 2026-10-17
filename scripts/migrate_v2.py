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
    with checked_connection(owner, owner=True) as c:
        c.execute("SELECT pg_advisory_xact_lock(61720261017)")
        # Bootstrap migration journal without applying destructive data changes.
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
                "INSERT INTO agent_runtime.schema_migrations(version,digest) VALUES (%s,%s)",
                (path.name, digest),
            )
        c.execute("GRANT USAGE ON SCHEMA agent_runtime TO insightflow_runtime")
        c.execute(
            "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA agent_runtime TO insightflow_runtime"
        )
        c.execute("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA agent_runtime TO insightflow_runtime")
        c.execute("REVOKE ALL ON agent_runtime.schema_migrations FROM insightflow_runtime")
        empty = c.execute("SELECT count(*) FROM business.orders").fetchone()[0] == 0
    if seed_empty and empty:
        seed(owner)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-empty", action="store_true")
    args = parser.parse_args()
    d = {**dotenv_values(ROOT / ".env"), **os.environ}
    for name in ("INSIGHTFLOW_ADMIN_DATABASE_URL", "INSIGHTFLOW_TEST_ADMIN_DATABASE_URL"):
        if d.get(name):
            migrate(d[name], args.seed_empty)
    print("Versioned additive migrations applied; existing business rows retained.")


if __name__ == "__main__":
    main()
