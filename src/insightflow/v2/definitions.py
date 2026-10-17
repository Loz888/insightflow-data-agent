from insightflow.retrieval.glossary import METRICS as V1_METRICS, METRIC_TABLES as V1_TABLES

METRICS = {
    **V1_METRICS,
    "delivered_order_count": "已支付且有delivered配送事件的订单数；同订单多事件只计一次；按订单时间归属。",
}
METRIC_TABLES = {**V1_TABLES, "delivered_order_count": ["orders", "shipping_events"]}
