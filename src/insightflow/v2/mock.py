"""Offline rule provider only. Never instantiated by the live path; never loads evaluation files."""

import re
from insightflow.v2.contracts import Decision, QueryPlan, Action, Answer
from insightflow.v2.semantics import AGGREGATIONS, explicit_windows, shift_month, REGIONS, reference_sql
from insightflow.v2.errors import Fault


class OfflineProvider:
    source = "mock"

    def __init__(self, clock):
        self.clock = clock

    async def request(self, task, payload, schema, budget):
        if task == "plan":
            q = payload["question"]
            old = payload.get("previous") or {}
            if re.search(r"第二个|那个|它们|怎么办|多少钱啊|未知指标", q):
                return Decision(disposition="clarify", message="请明确指标或指代对象。")
            if re.search(r"删除|drop\b|pg_sleep|pg_read_file|密码|api.?key|忽略.*指令", q, re.I):
                return Decision(disposition="reject", message="未授权操作。")
            metric = old.get("metric")
            mapping = [
                ("退款金额率", "refund_amount_rate"),
                ("退款订单率", "refunded_order_rate"),
                ("退款率", "refunded_order_rate"),
                ("退款金额", "refund_amount"),
                ("客单价", "average_order_value"),
                ("GMV", "gmv"),
                ("销售额", "paid_revenue"),
                ("营收", "paid_revenue"),
                ("已支付订单", "paid_order_count"),
                ("待支付订单", "pending_order_count"),
                ("取消订单", "cancelled_order_count"),
                ("订单数", "order_count"),
                ("订单数量", "order_count"),
                ("成交单数", "order_count"),
                ("客户数", "customer_count"),
                ("顾客数", "customer_count"),
                ("商品数", "product_count"),
                ("平均标价", "average_price"),
                ("最高标价", "max_price"),
                ("最低标价", "min_price"),
            ]
            for word, m in mapping:
                if word.lower() in q.lower():
                    metric = m
                    break
            if metric is None:
                return Decision(disposition="clarify", message="请说明受支持指标。")
            data = dict(old) if old else {}
            data.update(metric=metric, aggregation=AGGREGATIONS[metric])
            try:
                windows = explicit_windows(q, self.clock)
            except Fault as exc:
                return Decision(disposition="clarify", message=exc.message)
            if windows is not None:
                data["windows"] = [w.model_dump() for w in windows]
            elif re.search(r"全部|全量|所有时间|不限时间", q):
                data["windows"] = []
            regions = [n for n in REGIONS if n in q]
            if regions:
                excluded = bool(re.search(r"排除|不含|不包括|除.*以外|除.*之外|不要", q))
                data["exclude_regions" if excluded else "include_regions"] = regions
                data["include_regions" if excluded else "exclude_regions"] = []
            elif "全国" in q or "全部地区" in q:
                data.update(include_regions=[], exclude_regions=[])
            dim = None
            for word, d in [
                ("各地区", "region"),
                ("按地区", "region"),
                ("各月", "month"),
                ("按月", "month"),
                ("类别", "category"),
                ("商品排名", "product"),
            ]:
                if word in q:
                    dim = d
            data["dimension"] = dim
            top = re.search(r"(?:前|top\s*)(\d+)", q, re.I)
            data["top_n"] = int(top[1]) if top else None
            data["order"] = "asc" if re.search(r"最低|最少|升序", q) else "desc"
            data["comparison"] = "yoy" if "同比" in q else "mom" if "环比" in q else "none"
            data["comparison_window"] = None
            if data["comparison"] != "none":
                p = QueryPlan.model_validate({**data, "comparison": "none"})
                if len(p.windows) != 1:
                    return Decision(disposition="clarify", message="对比需要一个明确区间。")
                data["comparison_window"] = shift_month(
                    p.windows[0], -12 if data["comparison"] == "yoy" else -1
                ).model_dump()
            try:
                return Decision(
                    disposition="query", plan=QueryPlan.model_validate(data), summary="离线规则计划"
                )
            except ValueError:
                return Decision(disposition="clarify", message="组合超出支持范围。")
        if task == "action":
            p = QueryPlan.model_validate(payload["plan"])
            results = payload["tool_results"]
            i = len(results)
            names = [x["name"] for x in results if x["status"] == "ok"]
            if "schema" not in names:
                return Action(call_id=f"call{i}", name="schema", arguments={"query": payload["question"]})
            if "metric" not in names:
                return Action(call_id=f"call{i}", name="metric", arguments={"metric": p.metric})
            periods = {
                x.get("value", {}).get("period")
                for x in results
                if x["name"] == "execute_sql" and x["status"] == "ok"
            }
            if "current" not in periods:
                period = "current"
            elif p.comparison != "none" and "comparison" not in periods:
                period = "comparison"
            elif p.comparison != "none":
                return Action(
                    call_id=f"call{i}", name="compare", arguments={"evidence_id": payload["evidence_id"]}
                )
            else:
                raise Fault("MOCK_PROTOCOL")
            return Action(
                call_id=f"call{i}",
                name="execute_sql",
                arguments={"sql": reference_sql(p, period), "period": period},
            )
        if task == "answer":
            evidence = payload["evidence"]
            rows = evidence["rows"]
            citations = [
                {
                    "evidence_id": payload["evidence_id"],
                    "row": i,
                    "column": j,
                    "value": str(v) if v is not None else None,
                }
                for i, row in enumerate(rows[:5])
                for j, v in enumerate(row)
            ]
            if not citations:
                citations = [{"evidence_id": payload["evidence_id"], "row": 0, "column": 0, "value": None}]
            return Answer(
                explanation="以下为受控口径下的查询证据，不推断因果关系。",
                citations=citations,
                limitations=["离线规则模型，不代表真实模型能力。"],
            )
        raise Fault("UNKNOWN_TASK")

    async def close(self):
        pass
