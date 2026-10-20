import json
import math
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import sqlglot

SCORER_VERSION = "typed-bipartite-v2"
NUMERIC_OIDS = {20, 21, 23, 26, 700, 701, 1700}
MAX_MATCH_ROWS = 256
MAX_MATCH_WORK = 1_000_000


def column_kind(value):
    if value in NUMERIC_OIDS or value in ("numeric", "number", "integer", "decimal", "float"):
        return "number"
    if value in (16, "boolean", "bool"):
        return "bool"
    return "text"


def cell(value, kind=None):
    if value is None:
        return ("null", None)
    if isinstance(value, bool):
        return ("bool", value) if kind in (None, "bool") else ("invalid", None)
    # A string is numeric only when the independent reference declares that column numeric.
    if kind == "number" or kind is None and isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
            if number.is_finite():
                return ("number", number)
        except (InvalidOperation, ValueError):
            pass
        return ("invalid", None)
    if kind == "bool":
        return ("invalid", None)
    if isinstance(value, str):
        return ("text", value)
    return ("invalid", None)


def equivalent(actual, expected, ordered=False):
    columns = expected.get("columns")
    if not isinstance(columns, list) or actual.get("columns") != columns:
        return False
    left, right = actual.get("rows", []), expected.get("rows", [])
    if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
        return False
    types = expected.get("column_types")
    actual_types = actual.get("column_types")
    if types is not None:
        if len(types) != len(columns):
            return False
        kinds = [column_kind(t) for t in types]
        if actual_types is not None and (
            len(actual_types) != len(columns) or [column_kind(t) for t in actual_types] != kinds
        ):
            return False
    else:
        kinds = [None] * len(columns)
    if len(left) > MAX_MATCH_ROWS or len(left) ** 2 * max(1, len(columns)) > MAX_MATCH_WORK:
        raise ValueError("Result comparison exceeds the bounded matching budget")

    def normalize(rows):
        result = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) != len(columns):
                return None
            values = tuple(cell(v, k) for v, k in zip(row, kinds))
            if any(k == "invalid" for k, _ in values):
                return None
            result.append(values)
        return result

    left, right = normalize(left), normalize(right)
    if left is None or right is None:
        return False

    def compatible(row, reference):
        for a, b in zip(row, reference):
            if a[0] != b[0]:
                return False
            if a[0] == "number":
                if abs(a[1] - b[1]) > max(Decimal("0.00000001"), abs(b[1]) * Decimal("0.000000001")):
                    return False
            elif a[1] != b[1]:
                return False
        return True

    if ordered:
        return all(compatible(a, b) for a, b in zip(left, right))

    # Exact fields partition rows; multiplicity is retained. Tolerance is not transitive,
    # so numeric rows require one-to-one matching rather than sorting or rounding.
    def grouped(rows):
        groups = defaultdict(list)
        for row in rows:
            key = tuple((k, None if k == "number" else v) for k, v in row)
            groups[key].append(row)
        return groups

    lhs, rhs = grouped(left), grouped(right)
    if lhs.keys() != rhs.keys():
        return False
    for key, candidates in lhs.items():
        references = rhs[key]
        if len(candidates) != len(references):
            return False
        edges = [[j for j, b in enumerate(references) if compatible(a, b)] for a in candidates]
        matched = {}

        def augment(i, seen):
            for j in edges[i]:
                if j in seen:
                    continue
                seen.add(j)
                if j not in matched or augment(matched[j], seen):
                    matched[j] = i
                    return True
            return False

        if not all(augment(i, set()) for i in range(len(candidates))):
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
        "scorer_version": SCORER_VERSION,
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
