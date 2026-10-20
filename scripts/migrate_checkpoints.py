"""Operator-only LangGraph setup with a session advisory lock; no startup DDL by API roles."""

import argparse
from pathlib import Path
import os
import psycopg
from psycopg.rows import dict_row
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from langgraph.checkpoint.postgres import PostgresSaver
from dotenv import dotenv_values
from insightflow.database.connection import checked_connection


def migrate(owner):
    with checked_connection(owner, owner=True) as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS agent_checkpoints")
        c.execute("REVOKE ALL ON SCHEMA agent_checkpoints FROM PUBLIC")
    params = conninfo_to_dict(owner)
    params["options"] = "-c search_path=agent_checkpoints,pg_catalog"
    with psycopg.connect(make_conninfo(**params), autocommit=True, row_factory=dict_row) as c:
        c.execute("SELECT pg_advisory_lock(2026101902)")
        try:
            PostgresSaver(c).setup()
            c.execute("GRANT USAGE ON SCHEMA agent_checkpoints TO insightflow_runtime")
            c.execute(
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA agent_checkpoints TO insightflow_runtime"
            )
            c.execute(
                "REVOKE INSERT,UPDATE,DELETE ON agent_checkpoints.checkpoint_migrations FROM insightflow_runtime"
            )
        finally:
            c.execute("SELECT pg_advisory_unlock(2026101902)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-only", action="store_true")
    args = parser.parse_args()
    env = {**dotenv_values(Path(__file__).resolve().parents[1] / ".env"), **os.environ}
    names = (
        ["INSIGHTFLOW_TEST_ADMIN_DATABASE_URL"]
        if args.test_only
        else ["INSIGHTFLOW_ADMIN_DATABASE_URL", "INSIGHTFLOW_TEST_ADMIN_DATABASE_URL"]
    )
    for name in names:
        migrate(env[name])
    print("Locked checkpoint migrations applied by operator; runtime has no DDL permission.")
