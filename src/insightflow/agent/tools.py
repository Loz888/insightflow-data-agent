from insightflow.llm.base import Metric
import json
import logging
import time
from typing import Callable, TypeVar
from pydantic import BaseModel, Field, ConfigDict
from insightflow.database.errors import AgentError

log = logging.getLogger("insightflow.tools")

T = TypeVar("T")


class SQLInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sql: str = Field(min_length=1, max_length=8000)


class TableInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    table_name: str = Field(pattern=r"^(customers|products|orders|order_items|refunds)$")


class MetricInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: Metric


class Tools:
    def __init__(self, catalog, executor):
        self.catalog = catalog
        self.executor = executor

    def list_tables(self):
        return sorted(self.catalog)

    def get_table_schema(self, table_name):
        return self.catalog[TableInput(table_name=table_name).table_name].model_dump()

    def get_metric_definition(self, metric):
        from insightflow.retrieval.glossary import METRICS

        return METRICS[MetricInput(metric=metric).metric]

    def execute_readonly_sql(self, sql):
        return self.executor.execute(SQLInput(sql=sql).sql)

    def measured(self, state, node, tool, call: Callable[[], T]) -> T:
        started = time.perf_counter()
        error = None
        try:
            return call()
        except AgentError as exc:
            error = exc.kind.value
            raise
        finally:
            log.info(
                json.dumps(
                    {
                        "request_id": state["request_id"],
                        "session_id": state["session_id"],
                        "node_name": node,
                        "tool_name": tool,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                        "error_kind": error,
                    },
                    ensure_ascii=False,
                )
            )
