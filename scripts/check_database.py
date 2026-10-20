"""Check the frozen core fixture and the explicitly selected authorized schema."""

import argparse
import json
import os
from insightflow.database.connection import checked_connection
from insightflow.database.metadata import read_catalog

CORE_COUNTS = {"customers": 100, "products": 30, "orders": 500, "order_items": 1001, "refunds": 165}
V2_TABLES = {"shipping_events", "campaigns", "campaign_daily", "inventory_snapshots", "supplier_quotes"}


def check(reader, profile):
    expected = set(CORE_COUNTS) | (V2_TABLES if profile == "v2" else set())
    with checked_connection(reader, test_only=True) as conn:
        counts = {
            name: conn.execute("SELECT count(*) FROM business." + name).fetchone()[0] for name in CORE_COUNTS
        }
        for table in sorted(expected):
            privileges = conn.execute(
                "SELECT has_table_privilege(current_user,%s,'SELECT'),has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE,TRUNCATE')",
                ("business." + table, "business." + table),
            ).fetchone()
            assert privileges == (True, False), "Reader privileges unsafe"
        assert (
            conn.execute("SELECT has_schema_privilege(current_user,'business','CREATE')").fetchone()[0]
            is False
        )
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
        granted = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.table_privileges WHERE grantee=current_user AND table_schema='business' AND privilege_type='SELECT'"
            ).fetchall()
        }
        assert granted == expected, "Reader has unexpected business table access"
    assert counts == CORE_COUNTS, "Unexpected deterministic dataset"
    assert set(read_catalog(reader)) == set(CORE_COUNTS), "Original five-table catalog changed"
    return {
        "database": "insightflow_test",
        "reader": "insightflow_reader",
        "profile": profile,
        "counts": counts,
        "authorized_tables": sorted(expected),
        "permissions": "PASS",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("v1", "v2"), default="v2")
    args = parser.parse_args()
    print(json.dumps(check(os.environ["INSIGHTFLOW_TEST_DATABASE_URL"], args.profile)))


if __name__ == "__main__":
    main()
