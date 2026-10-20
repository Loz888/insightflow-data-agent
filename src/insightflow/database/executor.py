import json
from decimal import Decimal
import psycopg
from psycopg_pool import ConnectionPool, PoolTimeout
from insightflow.agent.cancellation import Cancellation, CURRENT_CANCELLATION
from insightflow.database.connection import checked_connection
from insightflow.database.errors import AgentError, ErrorKind, classify_db_error
from insightflow.database.validator import SQLValidator


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (tuple, list)):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        return {k: json_value(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    return value.isoformat()


class ReadonlyExecutor:
    def __init__(self, settings, catalog):
        dsn = settings.database_url.get_secret_value()
        with checked_connection(dsn):
            pass
        self.settings = settings
        self.validator = SQLValidator(catalog)

        def configure(conn):
            conn.read_only = True
            conn.execute("SET search_path=pg_catalog,business")

        self.pool = ConnectionPool(
            dsn,
            configure=configure,
            min_size=0,
            max_size=settings.pool_size,
            timeout=3,
            kwargs={"autocommit": True, "connect_timeout": 3},
            open=True,
        )

    def execute(self, sql, cancellation=None):
        token = cancellation or CURRENT_CANCELLATION.get() or Cancellation()
        token.check()
        validated = self.validator.validate(sql)  # mandatory even when caller already validated
        try:
            with (
                self.pool.connection() as conn,
                token.bind(lambda: conn.cancel_safe(timeout=1)),
                conn.transaction(),
            ):
                token.check()
                if self.settings.tenant_id is not None:
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                conn.execute(
                    "SELECT set_config('statement_timeout',%s,true)",
                    (str(self.settings.statement_timeout_ms),),
                )
                conn.execute(
                    "SELECT set_config('lock_timeout',%s,true)", (str(self.settings.lock_timeout_ms),)
                )
                conn.execute("SET LOCAL idle_in_transaction_session_timeout='3000ms'")
                conn.execute("SET LOCAL search_path=pg_catalog,business")
                if self.settings.tenant_id is not None:
                    # Trusted server identity only; generated SQL cannot call set_config.
                    conn.execute(
                        "SELECT set_config('insightflow.tenant_id',%s,true)", (self.settings.tenant_id,)
                    )
                conn.execute("SET LOCAL TIME ZONE 'UTC'")
                token.check()
                plan = conn.execute("EXPLAIN (FORMAT JSON) " + validated.sql).fetchone()[0][0]["Plan"]
                if plan["Total Cost"] > 100000 or plan["Plan Rows"] > 100000:
                    raise AgentError(ErrorKind.SQL_VALIDATION_ERROR, "查询计划超出资源预算。")
                with conn.cursor(name="bounded_result") as cursor:
                    token.check()
                    cursor.execute(validated.sql)
                    columns = [c.name for c in cursor.description] if cursor.description else None
                    rows = cursor.fetchmany(self.settings.max_rows + 1)
                    if columns is None:
                        columns = [c.name for c in cursor.description]
                    if len(rows) > self.settings.max_rows:
                        raise AgentError(ErrorKind.SQL_EXECUTION_ERROR, "查询结果超过行数上限，请增加筛选。")
                    result = {"columns": columns, "rows": json_value(rows), "row_count": len(rows)}
                    if self.settings.tenant_id is not None:
                        observed, snapshot = conn.execute(
                            "SELECT transaction_timestamp(),pg_current_snapshot()::text"
                        ).fetchone()
                        result["observed_at"] = observed.isoformat()
                        result["database_snapshot"] = snapshot
                    if len(json.dumps(result, ensure_ascii=False).encode()) > self.settings.max_bytes:
                        raise AgentError(ErrorKind.SQL_EXECUTION_ERROR, "查询结果超过字节上限，请缩小范围。")
                    token.check()
                    return result
        except (psycopg.Error, PoolTimeout) as exc:
            token.check()
            raise classify_db_error(exc) from None

    def close(self):
        self.pool.close()
