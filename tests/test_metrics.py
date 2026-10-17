import json
from pathlib import Path
import pytest
from insightflow.database.connection import checked_connection


@pytest.mark.integration
def test_independent_ground_truth_and_metrics(database_urls):
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "evaldata/questions.json").read_text())
    assert len(cases) == 30
    assert {k: sum(c["difficulty"] == k for c in cases) for k in ("basic", "join", "complex", "multi")} == {
        "basic": 10,
        "join": 10,
        "complex": 5,
        "multi": 5,
    }
    with checked_connection(database_urls[0], test_only=True) as conn:
        for case in cases:
            cur = conn.execute(case["reference_sql"])
            from decimal import Decimal

            rows = [[str(v) if isinstance(v, Decimal) else v for v in row] for row in cur.fetchall()]
            assert rows == case["expected_result"]["rows"], case["case_id"]
        orders = conn.execute(
            "SELECT id FROM business.orders WHERE status='paid' AND ordered_at>='2026-09-01' AND ordered_at<'2026-10-01'"
        ).fetchall()
        ids = {r[0] for r in orders}
        amounts = conn.execute("SELECT order_id,quantity,unit_price FROM business.order_items").fetchall()
        refunds = conn.execute(
            "SELECT order_id,refund_amount FROM business.refunds WHERE status='succeeded'"
        ).fetchall()
        revenue = sum((Decimal(q) * p for oid, q, p in amounts if oid in ids), Decimal(0))
        returned = sum((a for oid, a in refunds if oid in ids), Decimal(0))
        refunded_orders = {oid for oid, a in refunds if oid in ids}
        assert Decimal(cases[20]["expected_result"]["rows"][0][0]) == pytest.approx(
            Decimal(len(refunded_orders)) / len(ids)
        )
        assert Decimal(cases[21]["expected_result"]["rows"][0][0]) == returned
        assert Decimal(cases[22]["expected_result"]["rows"][0][0]) == pytest.approx(returned / revenue)
        assert Decimal(cases[23]["expected_result"]["rows"][0][0]) == pytest.approx(revenue / len(ids))
        assert len(refunded_orders) < sum(1 for oid, a in refunds if oid in ids)  # multiple refunds exist
