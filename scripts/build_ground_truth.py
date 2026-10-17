"""Independent trusted ReferenceSQL execution; never imports agent or Mock SQL."""

import json
import os
from decimal import Decimal
from pathlib import Path
from insightflow.database.connection import checked_connection

ROOT = Path(__file__).resolve().parents[1]


def normalize(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def build(dsn):
    cases = json.loads((ROOT / "evaldata/questions.json").read_text())
    results = {}
    with checked_connection(dsn, test_only=True) as conn:
        conn.execute("SET LOCAL TIME ZONE 'UTC'")
        for case in cases:
            cursor = conn.execute(case["reference_sql"])
            result = {"columns": [c.name for c in cursor.description], "rows": normalize(cursor.fetchall())}
            case["expected_result"] = result
            results[case["case_id"]] = result
    (ROOT / "evaldata/questions.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    (ROOT / "evaldata/expected_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n"
    )
    print("Independent ReferenceSQL executed:", len(cases))


if __name__ == "__main__":
    build(os.environ["INSIGHTFLOW_TEST_DATABASE_URL"])
