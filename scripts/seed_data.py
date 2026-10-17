"""Deterministic RESET loading; allowed only on the two exact InsightFlow DBs."""

import argparse
import os
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from insightflow.database.connection import checked_connection

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def seed(dsn, initialize=False, random_seed=20261020):
    rng = random.Random(random_seed)
    with checked_connection(dsn, owner=True) as conn:
        if initialize:
            for p in sorted((ROOT / "migrations").glob("*.sql")):
                conn.execute(p.read_text())
        conn.execute(
            "TRUNCATE business.refunds,business.order_items,business.orders,business.products,business.customers"
        )
        regions = ["华东", "华南", "华北", "西部"]
        for i in range(1, 101):
            conn.execute(
                "INSERT INTO business.customers VALUES (%s,%s,%s,%s)",
                (i, f"Customer-{i:03}", regions[(i - 1) % 4], REFERENCE - timedelta(days=400 + i)),
            )
        prices = {}
        for i in range(1, 31):
            prices[i] = Decimal(20 + i * 7)
            conn.execute(
                "INSERT INTO business.products VALUES (%s,%s,%s,%s)",
                (i, f"Product-{i:02}", ["办公", "电子", "家居"][(i - 1) % 3], prices[i]),
            )
        item_id = refund_id = 0
        for i in range(1, 501):
            status = ["paid", "paid", "paid", "paid", "pending", "cancelled"][i % 6]
            date = REFERENCE - timedelta(days=1 + (i * 7) % 120, hours=i % 24)
            conn.execute(
                "INSERT INTO business.orders VALUES (%s,%s,%s,%s)", (i, rng.randint(1, 100), date, status)
            )
            total = Decimal(0)
            for _ in range(1 + i % 3):
                item_id += 1
                pid = rng.randint(1, 30)
                qty = rng.randint(1, 4)
                price = prices[pid]
                total += price * qty
                conn.execute(
                    "INSERT INTO business.order_items VALUES (%s,%s,%s,%s,%s)", (item_id, i, pid, qty, price)
                )
            if status == "paid" and i % 5 == 0:
                # Split refunds and full/partial refunds; successful total never exceeds sale.
                parts = [total / 2, total / 2] if i % 10 == 0 else [total / 4]
                for part in parts:
                    refund_id += 1
                    conn.execute(
                        "INSERT INTO business.refunds VALUES (%s,%s,%s,%s,%s)",
                        (refund_id, i, part.quantize(Decimal(".01")), date + timedelta(days=2), "succeeded"),
                    )
                refund_id += 1
                conn.execute(
                    "INSERT INTO business.refunds VALUES (%s,%s,%s,%s,%s)",
                    (refund_id, i, Decimal("1.00"), date + timedelta(days=3), "failed"),
                )
        return {"customers": 100, "products": 30, "orders": 500, "order_items": item_id, "refunds": refund_id}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--initialize", action="store_true")
    args = parser.parse_args()
    for key in ("INSIGHTFLOW_ADMIN_DATABASE_URL", "INSIGHTFLOW_TEST_ADMIN_DATABASE_URL"):
        print(key.replace("DATABASE_URL", "database") + ":", seed(os.environ[key], args.initialize))
