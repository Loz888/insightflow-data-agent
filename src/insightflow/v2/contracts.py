from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from insightflow.llm.base import Metric as V1Metric

Metric = V1Metric | Literal["delivered_order_count"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Window(Strict):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered(self):
        if self.start.tzinfo is None or self.end.tzinfo is None or self.start >= self.end:
            raise ValueError("timezone-aware nonempty half-open interval required")
        return self


Region = Literal["华东", "华南", "华北", "西部"]


class QueryPlan(Strict):
    metric: Metric
    aggregation: Literal["count", "sum", "average", "ratio", "min", "max"]
    windows: list[Window] = Field(default_factory=list, max_length=12)
    include_regions: list[Region] = Field(default_factory=list, max_length=4)
    exclude_regions: list[Region] = Field(default_factory=list, max_length=4)
    dimension: Literal["region", "month", "category", "product", "customer"] | None = None
    order: Literal["asc", "desc"] = "desc"
    top_n: int | None = Field(None, ge=1, le=10)
    comparison: Literal["none", "yoy", "mom", "period"] = "none"
    comparison_window: Window | None = None
    currency: Literal["CNY"] = "CNY"
    timezone: Literal["UTC"] = "UTC"
    metric_version: Literal["2026-10-v1"] = "2026-10-v1"
    data_version: Literal["v1-seed20261020"] = "v1-seed20261020"

    @model_validator(mode="after")
    def coherent(self):
        if set(self.include_regions) & set(self.exclude_regions):
            raise ValueError("region include/exclude conflict")
        if (self.comparison == "none") != (self.comparison_window is None):
            raise ValueError("comparison requires exactly one comparison_window")
        if self.comparison != "none" and (len(self.windows) != 1 or self.dimension):
            raise ValueError("comparison supports one window and scalar metrics")
        if self.top_n is not None and self.dimension is None:
            raise ValueError("Top N requires dimension")
        for i, w in enumerate(self.windows):
            if any(w.start < x.end and x.start < w.end for x in self.windows[:i]):
                raise ValueError("overlapping windows")
        return self


class Decision(Strict):
    disposition: Literal["query", "clarify", "reject"]
    plan: QueryPlan | None = None
    message: str = Field(default="", max_length=400)
    summary: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def shape(self):
        if (self.disposition == "query") != (self.plan is not None):
            raise ValueError("query requires plan; non-query must not include plan")
        return self


class SchemaArgs(Strict):
    query: str = Field(min_length=1, max_length=1000)


class MetricArgs(Strict):
    metric: Metric


class SQLArgs(Strict):
    period: Literal["current", "comparison"] = "current"
    sql: str = Field(min_length=1, max_length=8000)


class CompareArgs(Strict):
    evidence_id: str = Field(min_length=1, max_length=80)


class Action(Strict):
    call_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    name: Literal["schema", "metric", "validate_sql", "execute_sql", "compare"]
    arguments: dict
    summary: str = Field(default="", max_length=200)


class Citation(Strict):
    evidence_id: str
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    value: str | int | None


class Answer(Strict):
    # Model writes prose segments; numeric values are rendered from server evidence only.
    explanation: str = Field(max_length=1000)
    citations: list[Citation] = Field(min_length=1, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=6)


class ToolResult(Strict):
    call_id: str
    name: str
    source: Literal["model", "mock"]
    status: Literal["ok", "error"]
    input_digest: str
    result_ref: str
    value: dict


class ChatInput(Strict):
    session_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    question: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")
