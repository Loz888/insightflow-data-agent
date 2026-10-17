from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field


Metric = Literal[
    "customer_count",
    "product_count",
    "order_count",
    "paid_order_count",
    "pending_order_count",
    "cancelled_order_count",
    "average_price",
    "max_price",
    "min_price",
    "paid_revenue",
    "gmv",
    "refunded_order_rate",
    "refund_amount",
    "refund_amount_rate",
    "average_order_value",
]


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Metric
    month: str | None = Field(None, pattern=r"^2026-(0[1-9]|1[0-2])$")
    region: Literal["华东", "华南", "华北", "西部"] | None = None
    group: Literal["region", "category", "product", "customer", "month"] | None = None
    top: int | None = Field(None, ge=1, le=10)
    currency: Literal["CNY"] = "CNY"


class Generation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1, max_length=8000)


class LLMProvider(Protocol):
    model_type: str

    def understand(self, question: str, previous: dict) -> Plan: ...
    def generate(self, plan: Plan, context: str, feedback: str | None) -> Generation: ...
    def usage(self) -> dict: ...
