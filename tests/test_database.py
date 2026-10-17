import hashlib
import psycopg
import pytest
from insightflow.database.connection import checked_connection
from insightflow.database.metadata import read_catalog


def snapshot(dsn):
    with checked_connection(dsn, owner=True, test_only=True) as conn:
        return hashlib.sha256(
            repr(
                [
                    conn.execute("SELECT * FROM business." + t + " ORDER BY id").fetchall()
                    for t in ("customers", "products", "orders", "order_items", "refunds")
                ]
            ).encode()
        ).hexdigest()


@pytest.mark.integration
def test_replay_schema_constraints_indexes(database_urls):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "seed", Path(__file__).resolve().parents[1] / "scripts/seed_data.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    reader, owner = database_urls
    before = snapshot(owner)
    counts = module.seed(owner)
    assert snapshot(owner) == before
    assert counts["orders"] == 500 and counts["customers"] == 100 and counts["products"] == 30
    assert len(read_catalog(reader)) == 5
    with checked_connection(owner, owner=True, test_only=True) as conn:
        assert conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname='business'").fetchone()[0] >= 11
        assert (
            conn.execute(
                "SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='business' AND constraint_type='FOREIGN KEY'"
            ).fetchone()[0]
            == 4
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute("UPDATE business.order_items SET quantity=0 WHERE id=1")


def test_wrong_db_rejected_before_connect():
    with pytest.raises(ValueError):
        checked_connection("dbname=agent_runtime user=insightflow_reader")


@pytest.mark.integration
def test_reader_is_non_owner_low_privilege(database_urls):
    with checked_connection(database_urls[0], test_only=True) as conn:
        row = conn.execute(
            "SELECT current_user, has_table_privilege(current_user,'business.orders','SELECT'), has_table_privilege(current_user,'business.orders','UPDATE')"
        ).fetchone()
        assert row == ("insightflow_reader", True, False)
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
