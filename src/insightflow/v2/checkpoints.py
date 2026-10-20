"""Checkpoint state is recovery data, never confirmed session facts or authorization."""

from contextvars import ContextVar
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

WORKFLOW_VERSION = "pilot-graph-v1"
CURRENT_BUDGET = ContextVar("insightflow_request_budget")


async def open_saver(dsn):
    pool = AsyncConnectionPool(
        dsn,
        min_size=0,
        max_size=2,
        timeout=2,
        open=False,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "connect_timeout": 3,
            "options": "-c search_path=agent_checkpoints,pg_catalog -c statement_timeout=2500 -c lock_timeout=1500",
        },
    )
    await pool.open(wait=True)
    try:
        async with pool.connection() as c:
            row = await (await c.execute("SELECT max(v) AS version FROM checkpoint_migrations")).fetchone()
            if row["version"] != len(AsyncPostgresSaver.MIGRATIONS) - 1:
                raise ValueError("Operator checkpoint migration required")
    except BaseException:
        await pool.close()
        raise
    serde = JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=[
            ("insightflow.v2.contracts", name)
            for name in ["QueryPlan", "Window", "Decision", "Action", "Answer"]
        ],
    )
    return pool, AsyncPostgresSaver(pool, serde=serde)
