from insightflow.database.metadata import read_catalog
from insightflow.retrieval.glossary import METRICS

DESCRIPTIONS = {
    "customers": "客户 customer 地区 region 华东 华南 华北 西部",
    "products": "商品 product 类别 category 标价 price",
    "orders": "订单 order 已支付 paid pending cancelled 时间 月份",
    "order_items": "订单明细 item 销售收入 revenue GMV 数量 单价",
    "refunds": "退款 refund 退款金额 成功退款 succeeded 退款率",
}


class SchemaCatalog:
    def __init__(self, dsn):
        self.tables = read_catalog(dsn)
        self.descriptions = DESCRIPTIONS
        self.metric_definitions = METRICS
        self.example_queries = {
            "orders": "SELECT count(*) AS value FROM business.orders",
            "products": "SELECT category,count(*) FROM business.products GROUP BY category",
        }
