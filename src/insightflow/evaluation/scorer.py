import json
import math
from collections import Counter
from decimal import Decimal, InvalidOperation
import sqlglot


def cell(value):
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value)
    try:
        number = Decimal(str(value))
        if number.is_finite():
            return ("number", number)
    except InvalidOperation:
        pass
    return ("text", str(value))


def equivalent(actual, expected, ordered=False):
    if actual.get("columns") != expected.get("columns"):
        return False
    left, right = actual.get("rows", []), expected.get("rows", [])
    if len(left) != len(right):
        return False
    if not ordered:

        def key(row):
            return tuple((c[0], str(c[1])) for c in map(cell, row))

        left = sorted(left, key=key)
        right = sorted(right, key=key)
    for row, reference in zip(left, right):
        if len(row) != len(reference):
            return False
        for a, b in zip(row, reference):
            a, b = cell(a), cell(b)
            if a[0] != b[0]:
                return False
            if a[0] == "number":
                if abs(a[1] - b[1]) > max(Decimal("0.00000001"), abs(b[1]) * Decimal("0.000000001")):
                    return False
            elif a[1] != b[1]:
                return False
    return True


def exact_sql(left, right):
    try:
        return sqlglot.parse_one(left, read="postgres").sql(dialect="postgres") == sqlglot.parse_one(
            right, read="postgres"
        ).sql(dialect="postgres")
    except sqlglot.errors.ParseError:
        return False


def grounded(answer, independent_execution):
    evidence = answer.get("evidence", {})
    if not equivalent(evidence, independent_execution, ordered=True):
        return False
    text = answer.get("answer", "")
    if not independent_execution.get("rows") or any(
        v is None for row in independent_execution["rows"] for v in row
    ):
        return text.startswith("证据不足")
    if not text.startswith("查询结果："):
        return False
    try:
        claim = json.loads(text.removeprefix("查询结果："))
        return equivalent(claim, independent_execution, ordered=True)
    except (ValueError, TypeError):
        return False


def summarize(records):
    if not records:
        raise ValueError("No evaluation observations")
    n = len(records)
    durations = sorted(r["duration_ms"] for r in records)

    def rate(key):
        return sum(bool(r[key]) for r in records) / n

    def percentile(p):
        return durations[math.ceil(n * p) - 1]

    return {
        "cases": n,
        "model_type": records[0]["model_type"],
        "sql_exact_match_rate": rate("sql_exact_match"),
        "sql_execution_rate": rate("sql_executed"),
        "sql_result_accuracy": rate("result_correct"),
        "answer_groundedness": rate("answer_grounded"),
        "success_rate": rate("scenario_success"),
        "p50_ms": percentile(0.5),
        "p95_ms": percentile(0.95),
        "average_retry_count": sum(r["retries"] for r in records) / n,
        "model_call_count": sum(r["model_calls"] for r in records),
        "token_usage_known_cases": sum(r["token_usage_known"] for r in records),
        "input_tokens": sum(r["input_tokens"] for r in records)
        if all(r["token_usage_known"] for r in records)
        else None,
        "output_tokens": sum(r["output_tokens"] for r in records)
        if all(r["token_usage_known"] for r in records)
        else None,
        "error_distribution": dict(Counter(r["error_kind"] for r in records if r["error_kind"])),
        "real_deepseek": "NOT RUN" if records[0]["model_type"] == "mock" else "RUN",
    }
