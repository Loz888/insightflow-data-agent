"""Prepare synthetic pilot data only in an explicitly owned ephemeral cluster.
Never a normal application startup step or production migration.
"""

from pathlib import Path
import os
from psycopg import sql
from insightflow.database.connection import checked_connection


def prepare(owner):
    if os.environ.get("INSIGHTFLOW_PILOT_OWNED_LAB") != "true":
        raise ValueError("Explicit owned ephemeral pilot lab required")
    root = Path(__file__).resolve().parents[1]
    with checked_connection(owner, owner=True) as c:
        for i in range(1, 21):
            c.execute(
                sql.SQL(
                    "CREATE TABLE IF NOT EXISTS business.{}(id bigint PRIMARY KEY,customer_id integer REFERENCES business.customers(id),note text NOT NULL)"
                ).format(sql.Identifier(f"pilot_aux_{i:02d}"))
            )
            c.execute(
                sql.SQL("GRANT SELECT ON business.{} TO insightflow_reader").format(
                    sql.Identifier(f"pilot_aux_{i:02d}")
                )
            )
        tables = [
            x[0] for x in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='business'").fetchall()
        ]
        if c.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='business' AND c.relrowsecurity LIMIT 1"
        ).fetchone():
            raise ValueError("Pilot fixture setup refuses an already RLS-enabled data source")
        for t in tables:
            c.execute(
                sql.SQL(
                    "ALTER TABLE business.{} ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT 'unassigned'"
                ).format(sql.Identifier(t))
            )
        c.execute("UPDATE business.customers SET tenant_id=CASE WHEN id<=40 THEN 'a' ELSE 'b' END")
        c.execute("UPDATE business.products SET tenant_id=CASE WHEN id<=10 THEN 'a' ELSE 'b' END")
        c.execute("UPDATE business.orders SET tenant_id=CASE WHEN customer_id<=40 THEN 'a' ELSE 'b' END")
        c.execute(
            "UPDATE business.order_items i SET tenant_id=o.tenant_id FROM business.orders o WHERE o.id=i.order_id"
        )
        c.execute(
            "UPDATE business.refunds r SET tenant_id=o.tenant_id FROM business.orders o WHERE o.id=r.order_id"
        )
        c.execute((root / "pilot_migrations/001_business_rls.sql").read_text())
