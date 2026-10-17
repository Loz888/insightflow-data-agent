"""Supported-language constraints and a deliberately bounded SQL contract verifier.
No arbitrary SQL equivalence claim. reference_sql is never an LLM fallback.
"""

import calendar
import re
from datetime import datetime, timedelta, timezone
import sqlglot
from insightflow.v2.contracts import QueryPlan, Window
from insightflow.v2.errors import Fault

UTC = timezone.utc
COVERAGE_START = datetime(2026, 6, 3, tzinfo=UTC)
COVERAGE_END = datetime(2026, 10, 1, tzinfo=UTC)
REGIONS = ("华东", "华南", "华北", "西部")
AGGREGATIONS = {
    "customer_count": "count",
    "product_count": "count",
    "order_count": "count",
    "paid_order_count": "count",
    "pending_order_count": "count",
    "cancelled_order_count": "count",
    "average_price": "average",
    "max_price": "max",
    "min_price": "min",
    "paid_revenue": "sum",
    "gmv": "sum",
    "refund_amount": "sum",
    "refunded_order_rate": "ratio",
    "refund_amount_rate": "ratio",
    "average_order_value": "average",
}


def month_window(year, month):
    start = datetime(year, month, 1, tzinfo=UTC)
    return Window(start=start, end=datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=UTC))


def shift_month(w, count):
    def shift(d):
        m = d.year * 12 + d.month - 1 + count
        y, m = divmod(m, 12)
        return d.replace(year=y, month=m + 1, day=min(d.day, calendar.monthrange(y, m + 1)[1]))

    return Window(start=shift(w.start), end=shift(w.end))


def explicit_windows(question, clock):
    # Whole UTC calendar days immediately preceding the reference day, excludes reference day.
    if re.search(r"(?:近|最近|过去)\s*\d+\s*天", question):
        n = int(re.search(r"(?:近|最近|过去)\s*(\d+)\s*天", question)[1])
        if not 1 <= n <= 366:
            raise Fault("CLARIFICATION", "相对日期仅支持1至366个完整UTC自然日。")
        end = clock.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return [Window(start=end - timedelta(days=n), end=end)]
    dates = re.findall(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", question)
    if dates:
        if len(dates) != 2:
            raise Fault("CLARIFICATION", "请给出两个ISO日期，起日包含、止日不包含。")
        try:
            return [
                Window(
                    start=datetime(*map(int, dates[0]), tzinfo=UTC),
                    end=datetime(*map(int, dates[1]), tzinfo=UTC),
                )
            ]
        except ValueError:
            raise Fault("CLARIFICATION", "日期范围无效。") from None
    months = re.findall(r"(?<!\d)(1[0-2]|0?[1-9])月", question)
    years = re.findall(r"(20\d{2})年", question)
    if len(set(years)) > 1:
        raise Fault("CLARIFICATION", "跨年多月请使用明确的ISO半开日期区间。")
    year = int(years[0]) if years else clock.year
    if months:
        values = [int(n) for n in months]
        if len(values) > 1 and re.search(r"至|到|~|～", question):
            if values[0] > values[-1]:
                raise Fault("CLARIFICATION", "跨年范围请使用ISO日期。")
            return [Window(start=month_window(year, values[0]).start, end=month_window(year, values[-1]).end)]
        return [month_window(year, m) for m in sorted(set(values))]
    if "上月" in question:
        return [shift_month(month_window(clock.year, clock.month), -1)]
    if "本月" in question or "这个月" in question:
        return [month_window(clock.year, clock.month)]
    if re.search(r"季度|去年|今年|昨天|今天|周|最近|近\d|过去", question):
        raise Fault("CLARIFICATION", "该日期表达不在支持范围，请明确日期区间。")
    return None


def guard_question(question, plan, previous, clock):
    """Verify explicit lexical constraints in addition to model-produced structured semantics.
    This is not a general natural-language theorem prover; ambiguous language is rejected.
    """
    if re.search(r"美元|美金|USD|CNY以外|因果|导致|为什么|预测|利润|利润率|留存|复购", question, re.I):
        raise Fault("CLARIFICATION", "币种、指标或因果要求超出已定义业务能力。")
    if re.search(
        r"删除|drop\b|pg_sleep|pg_read_file|忽略.*(?:指令|限制)|system prompt|api.?key|密码|系统表",
        question,
        re.I,
    ):
        raise Fault("SAFETY_DENIED", "请求涉及未授权操作或指令覆盖。")
    if plan.aggregation != AGGREGATIONS[plan.metric]:
        raise Fault("SEMANTIC_MISMATCH", "指标与聚合口径不一致。", True)
    windows = explicit_windows(question, clock)
    if windows is not None and plan.windows != windows:
        raise Fault("SEMANTIC_MISMATCH", "计划丢失或改变了明确日期范围。", True)
    if windows is None and previous and not re.search(r"全部|全量|所有时间|不限时间", question):
        if plan.windows != QueryPlan.model_validate(previous).windows:
            raise Fault("SEMANTIC_MISMATCH", "多轮日期约束被静默丢弃。", True)
    regions = [n for n in REGIONS if n in question]
    if regions:
        excluded = bool(re.search(r"排除|不含|不包括|除.*以外|除.*之外|不要", question))
        if (
            len(regions) > 1
            and re.search(r"排除|不含|不包括|不要", question)
            and re.search(r"仅|只看|包含", question)
        ):
            raise Fault("CLARIFICATION", "混合地区条件请明确包含集合与排除集合。")
        target = plan.exclude_regions if excluded else plan.include_regions
        if set(target) != set(regions) or (
            set(plan.include_regions if excluded else plan.exclude_regions) & set(regions)
        ):
            raise Fault("SEMANTIC_MISMATCH", "地区包含/排除条件不一致。", True)
    elif previous and "全国" not in question and "全部地区" not in question:
        old = QueryPlan.model_validate(previous)
        if old.include_regions != plan.include_regions or old.exclude_regions != plan.exclude_regions:
            raise Fault("SEMANTIC_MISMATCH", "多轮地区约束被静默丢弃。", True)
    for word, value in [("同比", "yoy"), ("环比", "mom")]:
        if word in question and plan.comparison != value:
            raise Fault("SEMANTIC_MISMATCH", "对比要求被静默丢弃。", True)
    if plan.comparison in ("yoy", "mom"):
        expected = shift_month(plan.windows[0], -12 if plan.comparison == "yoy" else -1)
        if plan.comparison_window != expected:
            raise Fault("SEMANTIC_MISMATCH", "对比区间与同/环比定义不一致。", True)
    top = re.search(r"(?:前|top\s*)(\d+)", question, re.I)
    if top and plan.top_n != int(top[1]):
        raise Fault("SEMANTIC_MISMATCH", "Top N要求不一致。", True)
    for word, dim in [
        ("各地区", "region"),
        ("按地区", "region"),
        ("各月", "month"),
        ("按月", "month"),
        ("类别", "category"),
    ]:
        if word in question and plan.dimension != dim:
            raise Fault("SEMANTIC_MISMATCH", "分组维度不一致。", True)
    if re.search(r"最低|最少|升序", question) and plan.order != "asc":
        raise Fault("SEMANTIC_MISMATCH", "排序方向不一致。", True)
    if plan.metric in ("customer_count", "product_count", "average_price", "max_price", "min_price"):
        if plan.windows or plan.comparison != "none":
            raise Fault("CLARIFICATION", "主数据指标没有订单日期口径。")
    else:
        for w in [*plan.windows, *([plan.comparison_window] if plan.comparison_window else [])]:
            if w.start < COVERAGE_START or w.end > COVERAGE_END:
                raise Fault("CLARIFICATION", "请求区间超出v1合成数据覆盖，不能把缺失区间当零计算同比。")
    if plan.dimension in ("category", "product") and plan.metric not in (
        "product_count",
        "average_price",
        "max_price",
        "min_price",
    ):
        raise Fault("CLARIFICATION", "订单按商品维度的分摊口径尚未支持。")
    if plan.dimension == "customer":
        raise Fault("CLARIFICATION", "客户级分组暂未支持，避免输出未经定义的细粒度信息。")
    reference_sql(plan)
    return plan


def _stamp(d):
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _predicate(windows):
    return " OR ".join(
        "(o.ordered_at >= CAST('%s' AS TIMESTAMPTZ) AND o.ordered_at < CAST('%s' AS TIMESTAMPTZ))"
        % (_stamp(w.start), _stamp(w.end))
        for w in windows
    )


def reference_sql(p, period="current"):
    """Trusted reference contract used ONLY to verify proposed SQL and offline reference tests.
    DeepSeek receives definitions/conventions, never this SQL or an expected answer.
    """
    m = p.metric
    if m in ("customer_count", "product_count", "average_price", "max_price", "min_price"):
        table = "customers" if m == "customer_count" else "products"
        alias = "c" if table == "customers" else "p"
        expression = {
            "customer_count": "COUNT(*)",
            "product_count": "COUNT(*)",
            "average_price": "AVG(p.price)",
            "max_price": "MAX(p.price)",
            "min_price": "MIN(p.price)",
        }[m]
        dimension = {"region": "c.region", "category": "p.category", "product": "p.name"}.get(p.dimension)
        if p.dimension and dimension is None:
            raise Fault("CLARIFICATION", "该主数据维度不支持。")
        if table == "products" and (p.include_regions or p.exclude_regions or p.dimension == "region"):
            raise Fault("CLARIFICATION", "商品没有客户地区归属。")
        source = f"business.{table} AS {alias}"
    else:
        dimension = {"region": "c.region", "month": "DATE_TRUNC('month', o.ordered_at)"}.get(p.dimension)
        if p.dimension and dimension is None:
            raise Fault("CLARIFICATION", "暂不支持该订单维度。")
        source = "business.orders AS o"
        if p.include_regions or p.exclude_regions or p.dimension == "region":
            source += " JOIN business.customers AS c ON o.customer_id = c.id"
        needs_sales = m in ("paid_revenue", "gmv", "refund_amount_rate", "average_order_value")
        needs_refunds = m in ("refund_amount", "refund_amount_rate", "refunded_order_rate")
        if needs_sales:
            source += " LEFT JOIN (SELECT order_id, SUM(quantity * unit_price) AS revenue FROM business.order_items GROUP BY order_id) AS s ON o.id = s.order_id"
        if needs_refunds:
            source += " LEFT JOIN (SELECT order_id, SUM(refund_amount) AS refunded FROM business.refunds WHERE status = 'succeeded' GROUP BY order_id) AS r ON o.id = r.order_id"
        expression = {
            "order_count": "COUNT(*)",
            "paid_order_count": "COUNT(*)",
            "pending_order_count": "COUNT(*)",
            "cancelled_order_count": "COUNT(*)",
            "paid_revenue": "COALESCE(SUM(s.revenue), 0)",
            "gmv": "COALESCE(SUM(s.revenue), 0)",
            "refund_amount": "COALESCE(SUM(r.refunded), 0)",
            "refunded_order_rate": "CAST(COUNT(r.order_id) AS NUMERIC) / NULLIF(COUNT(*), 0)",
            "refund_amount_rate": "COALESCE(SUM(r.refunded), 0) / NULLIF(SUM(s.revenue), 0)",
            "average_order_value": "SUM(s.revenue) / NULLIF(COUNT(*), 0)",
        }[m]
    terms = []
    if m not in ("customer_count", "product_count", "average_price", "max_price", "min_price"):
        windows = p.windows if period == "current" else [p.comparison_window]
        if windows:
            terms.append("(" + _predicate(windows) + ")")
        if m == "gmv":
            terms.append("o.status <> 'cancelled'")
        elif m != "order_count":
            status = {"pending_order_count": "pending", "cancelled_order_count": "cancelled"}.get(m, "paid")
            terms.append("o.status = '%s'" % status)
    for values, operator in [(p.include_regions, "IN"), (p.exclude_regions, "NOT IN")]:
        if values:
            terms.append("c.region " + operator + " (" + ", ".join("'%s'" % n for n in sorted(values)) + ")")
    sql = (
        "SELECT "
        + ((dimension + " AS dimension, ") if dimension else "")
        + expression
        + " AS value FROM "
        + source
    )
    if terms:
        sql += " WHERE " + " AND ".join(terms)
    if dimension:
        sql += " GROUP BY " + dimension + " ORDER BY value " + p.order.upper() + ", dimension ASC"
    if p.top_n:
        sql += " LIMIT " + str(p.top_n)
    return sql


class SemanticSQLGuard:
    def __init__(self, validator):
        self.validator = validator

    def validate(self, sql, plan, period="current"):
        if period == "comparison" and plan.comparison_window is None:
            raise Fault("SEMANTIC_MISMATCH", "不存在对比区间。")
        proposed = self.validator.validate(sql)
        expected = self.validator.validate(reference_sql(plan, period))

        # Qualification normalizes unqualified columns, casing and whitespace.
        # Alias names / expression structure must follow the documented canonical contract.
        def canonical(text):
            from sqlglot import exp

            tree = sqlglot.parse_one(text, read="postgres")
            # Normalize only proven local equivalences: redundant parentheses,
            # UTC representations of time bounds, COUNT(nonnullable physical PK).
            for node in reversed(list(tree.walk())):
                node.comments = None
                if isinstance(node, exp.Paren):
                    node.replace(node.this.copy())
                elif (
                    isinstance(node, exp.Count)
                    and isinstance(node.this, exp.Column)
                    and node.this.name == "id"
                    and node.this.table in ("o", "c", "p")
                    and not node.args.get("distinct")
                ):
                    node.set("this", exp.Star())
            for function in tree.find_all(exp.Anonymous):
                args = function.expressions
                if (
                    function.name.lower() == "count"
                    and len(args) == 1
                    and isinstance(args[0], exp.Column)
                    and args[0].name == "id"
                    and args[0].table in ("o", "c", "p")
                ):
                    function.set("expressions", [exp.Star()])
            for comparison in tree.find_all(exp.GTE, exp.LT):
                if isinstance(comparison.this, exp.Column) and comparison.this.name == "ordered_at":
                    rhs = comparison.expression
                    literal = rhs.this if isinstance(rhs, exp.Cast) else rhs
                    if isinstance(literal, exp.Literal) and literal.is_string:
                        try:
                            d = datetime.fromisoformat(literal.this.replace("Z", "+00:00"))
                            if d.tzinfo is None:
                                d = d.replace(tzinfo=UTC)
                            comparison.set(
                                "expression",
                                sqlglot.parse_one("CAST('%s' AS TIMESTAMPTZ)" % _stamp(d), read="postgres"),
                            )
                        except ValueError:
                            pass

            # AND/OR are commutative within their existing AST grouping.
            def ordered(node):
                if isinstance(node, (exp.And, exp.Or)):
                    members = list(node.flatten())
                    members.sort(key=lambda x: x.sql(dialect="postgres", normalize=True))
                    rebuilt = members[0].copy()
                    for item in members[1:]:
                        rebuilt = type(node)(this=rebuilt, expression=item.copy())
                    return rebuilt
                return node

            tree = tree.transform(ordered)
            return tree.sql(dialect="postgres", normalize=True)

        if canonical(proposed.sql) != canonical(expected.sql):
            raise Fault(
                "SEMANTIC_MISMATCH",
                "SQL与受支持计划契约不一致：核对指标聚合、半开日期、地区排除、维度、排序、Top N和预聚合；使用约定别名。",
                True,
            )
        return proposed
