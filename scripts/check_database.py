import json
import os
from insightflow.database.connection import checked_connection
from insightflow.database.metadata import read_catalog

reader = os.environ["INSIGHTFLOW_TEST_DATABASE_URL"]
with checked_connection(reader, test_only=True) as conn:
    counts = {
        name: conn.execute("SELECT count(*) FROM business." + name).fetchone()[0]
        for name in ("customers", "products", "orders", "order_items", "refunds")
    }
    for table in counts:
        privileges = conn.execute(
            "SELECT has_table_privilege(current_user,%s,'SELECT'),has_table_privilege(current_user,%s,'INSERT,UPDATE,DELETE,TRUNCATE')",
            ("business." + table, "business." + table),
        ).fetchone()
        assert privileges == (True, False), "Reader privileges unsafe"
    assert (
        conn.execute("SELECT has_schema_privilege(current_user,'business','CREATE')").fetchone()[0] is False
    )
    assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"
    granted = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.table_privileges WHERE grantee=current_user AND table_schema='business' AND privilege_type='SELECT'"
        ).fetchall()
    }
    assert granted == set(counts), "Reader has unexpected business table access"
assert counts == {"customers": 100, "products": 30, "orders": 500, "order_items": 1001, "refunds": 165}, (
    "Unexpected deterministic dataset"
)
assert len(read_catalog(reader)) == 5
print(
    json.dumps(
        {
            "database": "insightflow_test",
            "reader": "insightflow_reader",
            "counts": counts,
            "permissions": "PASS",
        }
    )
)
