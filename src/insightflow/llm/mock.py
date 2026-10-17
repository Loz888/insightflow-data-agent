"""Deterministic semantic/SQL strategy. Never reads evaluation answers or case IDs."""

import re
from insightflow.database.errors import AgentError, ErrorKind
from insightflow.llm.base import Generation, Plan


def parse_question(question: str, previous: dict) -> Plan:
    question = re.sub(r"\s+", "", question)
    metric = None
    for phrases, name in [
        (["退款金额率"], "refund_amount_rate"),
        (["退款订单率", "退款率", "退货率"], "refunded_order_rate"),
        (["退款金额"], "refund_amount"),
        (["客单价"], "average_order_value"),
        (["GMV", "gmv"], "gmv"),
        (["销售收入", "营收", "实收销售额"], "paid_revenue"),
        (["平均价格"], "average_price"),
        (["最高价格"], "max_price"),
        (["最低价格"], "min_price"),
        (["待支付订单"], "pending_order_count"),
        (["已取消订单"], "cancelled_order_count"),
        (["已支付订单"], "paid_order_count"),
        (["订单总数", "订单数", "订单数量"], "order_count"),
        (["客户总数"], "customer_count"),
        (["商品总数", "商品数量"], "product_count"),
    ]:
        if any(word in question for word in phrases):
            metric = name
            break
    explicit_metric = metric is not None
    followup = any(s in question for s in ("那", "改成", "呢"))
    if metric is None and followup:
        metric = previous.get("metric")
    if not metric:
        raise AgentError(
            ErrorKind.CLARIFICATION_REQUIRED, "缺少可支持的业务指标，请明确收入、订单数或退款率等口径。"
        )
    data = dict(previous) if followup else {}
    data["metric"] = metric
    explicit_year = re.search(r"(\d{4})年", question)
    unsupported = ("去年", "明年", "季度", "昨天", "今天", "近7天", "美元", "净收入", "净销售收入")
    if (
        (explicit_year and explicit_year[1] != "2026")
        or any(word in question for word in unsupported)
        or re.search(r"\d+日", question)
    ):
        raise AgentError(
            ErrorKind.CLARIFICATION_REQUIRED,
            "当前演示仅支持固定参考点的 2026 年整月、CNY 及已定义指标；请澄清范围。",
        )
    month_mentions = re.findall(r"(?:2026年|今年)?\s*(\d{1,2})\s*月", question)
    if len(month_mentions) > 1 or re.search(r"\d{1,2}[-~至到]\d{1,2}月", question):
        raise AgentError(
            ErrorKind.CLARIFICATION_REQUIRED, "当前只支持单个整月，请明确一个月份；不会静默缩小区间。"
        )
    match = re.search(r"(?:2026年|今年)?\s*(\d{1,2})\s*月", question)
    if match:
        data["month"] = f"2026-{int(match[1]):02}"
    if "上月" in question:
        data["month"] = "2026-09"
    elif "本月" in question:
        data["month"] = "2026-10"
    if "全部地区" in question:
        data["region"] = None
    if "所有月份" in question:
        data["month"] = None
    regions = [name for name in ("华东", "华南", "华北", "西部") if name in question]
    if len(regions) > 1:
        raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "请明确单个地区，或询问各地区比较。")
    if regions:
        data["region"] = regions[0]
    if "各地区" in question:
        data["group"] = "region"
        data["region"] = None
    if "各月份" in question:
        data["group"] = "month"
        data["month"] = None
    if "各类别" in question or "各商品类别" in question:
        data["group"] = "category"
    if "前5" in question:
        data["top"] = 5
        data["group"] = "customer" if "客户" in question else "product"
    if (
        followup
        and not explicit_metric
        and not (
            match
            or regions
            or any(word in question for word in ("上月", "本月", "全部地区", "所有月份", "各地区", "各月份"))
        )
    ):
        raise AgentError(
            ErrorKind.CLARIFICATION_REQUIRED, "无法可靠解析指代，请明确要更改的时间、地区或指标。"
        )
    if metric in ("refunded_order_rate", "refund_amount_rate", "refund_amount") and data.get("group") in (
        "category",
        "product",
    ):
        raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "退款记录没有商品粒度，不能将其归因到商品或类别。")
    if metric in ("customer_count", "product_count", "average_price", "max_price", "min_price") and (
        data.get("month") or data.get("region")
    ):
        raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "此指标暂不支持该时间/地区筛选口径。")
    try:
        return Plan.model_validate(data)
    except ValueError:
        raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "日期或业务约束不在演示支持范围内。") from None


def build_sql(plan: Plan) -> str:
    metric = plan.metric
    if metric in ("customer_count", "product_count", "average_price", "max_price", "min_price"):
        table = "customers" if metric == "customer_count" else "products"
        expr = {"average_price": "AVG(price)", "max_price": "MAX(price)", "min_price": "MIN(price)"}.get(
            metric, "COUNT(*)"
        )
        if plan.group == "category" and table == "products":
            return f"SELECT category AS dimension,{expr} AS value FROM business.products GROUP BY category ORDER BY dimension"
        if plan.group:
            raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "该指标不支持此分组。")
        return f"SELECT {expr} AS value FROM business.{table}"
    filters = []
    if metric in ("order_count", "gmv"):
        if metric == "gmv":
            filters.append("o.status <> 'cancelled'")
    else:
        status = {"pending_order_count": "pending", "cancelled_order_count": "cancelled"}.get(metric, "paid")
        filters.append(f"o.status = '{status}'")
    if plan.month:
        year, month = map(int, plan.month.split("-"))
        end = f"{year + 1}-01" if month == 12 else f"{year}-{month + 1:02}"
        filters.extend(
            [
                f"o.ordered_at >= TIMESTAMPTZ '{plan.month}-01 00:00:00+00'",
                f"o.ordered_at < TIMESTAMPTZ '{end}-01 00:00:00+00'",
            ]
        )
    if plan.region:
        filters.append(f"c.region = '{plan.region}'")
    where = " WHERE " + " AND ".join(filters) if filters else ""
    customers = (
        " JOIN business.customers c ON c.id=o.customer_id"
        if plan.region or plan.group in ("region", "customer")
        else ""
    )
    dimension = {
        "region": "c.region",
        "customer": "c.name",
        "month": "TO_CHAR(o.ordered_at AT TIME ZONE 'UTC','YYYY-MM')",
        "category": "p.category",
        "product": "p.name",
    }.get(plan.group)
    grouping = " GROUP BY " + dimension if dimension else ""
    ordering = (" ORDER BY value DESC,dimension" if plan.top else " ORDER BY dimension") if dimension else ""
    limit = f" LIMIT {plan.top}" if plan.top else ""
    selectdim = dimension + " AS dimension," if dimension else ""
    if metric.endswith("order_count") or metric == "order_count":
        if plan.group in ("product", "category"):
            raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "此订单口径不支持商品分组。")
        return f"SELECT {selectdim}COUNT(*) AS value FROM business.orders o{customers}{where}{grouping}{ordering}{limit}"
    if plan.group in ("category", "product"):
        if metric != "paid_revenue":
            raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "暂只支持按商品类别归属销售收入。")
        return f"SELECT {selectdim}SUM(i.quantity*i.unit_price) AS value FROM business.orders o JOIN business.order_items i ON i.order_id=o.id JOIN business.products p ON p.id=i.product_id{customers}{where}{grouping}{ordering}{limit}"
    # Aggregate one row per order before joining refunds: no item/refund fan-out.
    needs_items = metric in ("paid_revenue", "gmv", "refund_amount_rate", "average_order_value")
    needs_refunds = metric in ("refunded_order_rate", "refund_amount", "refund_amount_rate")
    ctes = []
    joins = ""
    if needs_items:
        ctes.append(
            "item_totals AS (SELECT order_id,SUM(quantity*unit_price) AS sale FROM business.order_items GROUP BY order_id)"
        )
        joins += " JOIN item_totals i ON i.order_id=o.id"
    if needs_refunds:
        ctes.append(
            "refund_totals AS (SELECT order_id,SUM(refund_amount) AS returned FROM business.refunds WHERE status='succeeded' GROUP BY order_id)"
        )
        joins += " LEFT JOIN refund_totals r ON r.order_id=o.id"
    cte = "WITH " + ",".join(ctes) + " "
    expression = {
        "paid_revenue": "COALESCE(SUM(i.sale),0)",
        "gmv": "COALESCE(SUM(i.sale),0)",
        "refunded_order_rate": "CAST(COUNT(r.order_id) AS NUMERIC)/NULLIF(COUNT(*),0)",
        "refund_amount": "COALESCE(SUM(r.returned),0)",
        "refund_amount_rate": "COALESCE(SUM(r.returned),0)/NULLIF(SUM(i.sale),0)",
        "average_order_value": "SUM(i.sale)/NULLIF(COUNT(*),0)",
    }[metric]
    return (
        cte
        + f"SELECT {selectdim}{expression} AS value FROM business.orders o{joins}{customers}{where}{grouping}{ordering}{limit}"
    )


class MockLLMProvider:
    model_type = "mock"

    def understand(self, question, previous):
        return parse_question(question, previous)

    def generate(self, plan, context, feedback):
        return Generation(sql=build_sql(plan))

    def usage(self):
        return {"input_tokens": None, "output_tokens": None, "token_usage_known": False}
