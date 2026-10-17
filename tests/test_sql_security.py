import hashlib
import time
import psycopg
import pytest
from pydantic import SecretStr
from insightflow.agent.service import AgentService
from insightflow.config import Settings
from insightflow.database.connection import checked_connection
from insightflow.database.errors import AgentError, ErrorKind, classify_db_error

ATTACKS = [
    "DROP TABLE business.orders",
    "UPDATE business.orders SET status='cancelled'",
    "DELETE FROM business.orders",
    "INSERT INTO business.orders VALUES(9999,1,now(),'paid')",
    "SELECT id FROM business.orders; DELETE FROM business.orders",
    "SELECT id INTO business.stolen FROM business.orders",
    "WITH changed AS (DELETE FROM business.orders RETURNING *) SELECT * FROM changed",
    "WITH changed AS (UPDATE business.orders SET status='paid' RETURNING *) SELECT * FROM changed",
    "SELECT id FROM business.orders UNION SELECT oid FROM pg_catalog.pg_authid",
    "SELECT * FROM pg_catalog.pg_authid",
    "SELECT * FROM other_schema.orders",
    "SELECT * FROM business.secret_payroll",
    "SELECT pg_read_file('/etc/passwd') FROM business.orders",
    "SELECT pg_sleep(10) FROM business.orders",
    "SELECT public.evil(id) FROM business.orders",
    "SELECT set_config('transaction_read_only','off',false) FROM business.orders",
    "SELECT dblink('secret','select 1') FROM business.orders",
    "SELECT * FROM generate_series(1,1000000000)",
    "SELECT * FROM business.orders FOR UPDATE",
    "SELECT id::regclass FROM business.orders",
    "SELECT * FROM business.orders a CROSS JOIN business.orders b",
    "SELECT * FROM business.orders a JOIN business.orders b ON true",
    "WITH RECURSIVE r AS (SELECT * FROM business.orders UNION ALL SELECT * FROM r) SELECT * FROM r",
    "COPY business.orders TO PROGRAM 'id'",
    "EXPLAIN ANALYZE SELECT * FROM business.orders",
]


@pytest.fixture
def secure(database_urls):
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    yield svc
    svc.close()


def digest(owner):
    with checked_connection(owner, owner=True, test_only=True) as conn:
        data = [
            conn.execute("SELECT * FROM business." + table + " ORDER BY id").fetchall()
            for table in ("customers", "products", "orders", "order_items", "refunds")
        ]
        return hashlib.sha256(repr(data).encode()).hexdigest()


@pytest.mark.integration
@pytest.mark.parametrize("sql", ATTACKS)
def test_ast_rejects_attacks(secure, sql):
    with pytest.raises(AgentError) as exc:
        secure.executor.execute(sql)
    assert exc.value.kind in (ErrorKind.SQL_VALIDATION_ERROR, ErrorKind.SQL_SYNTAX_ERROR)
    assert exc.value.message


@pytest.mark.integration
def test_attacks_preserve_all_business_data(secure, database_urls):
    before = digest(database_urls[1])
    for sql in ATTACKS:
        with pytest.raises(AgentError):
            secure.executor.execute(sql)
    assert digest(database_urls[1]) == before


@pytest.mark.integration
def test_independent_database_permissions_and_readonly(secure, database_urls):
    with checked_connection(database_urls[0], test_only=True) as conn:
        # Independent DB defenses still reject bypass attempts without the AST.
        for sql in ["SELECT * FROM pg_catalog.pg_authid", "CREATE TABLE business.not_allowed(id int)"]:
            with pytest.raises(psycopg.Error):
                with conn.transaction():
                    conn.execute(sql)
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with conn.transaction():
                conn.execute("DELETE FROM business.orders WHERE id=-1")
        conn.commit()
        conn.execute("SET default_transaction_read_only=off")
        conn.commit()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("DELETE FROM business.orders WHERE id=-1")
    with secure.executor.pool.connection() as conn, conn.transaction():
        assert conn.execute("SHOW transaction_read_only").fetchone()[0] == "on"
        assert conn.execute("SELECT current_user").fetchone()[0] == "insightflow_reader"
    assert secure.executor.pool.max_size == 2


@pytest.mark.integration
@pytest.mark.parametrize("statement,lock", [(50, 200), (1000, 50)])
def test_real_query_and_lock_timeout(database_urls, statement, lock):
    settings = Settings(
        database_url=SecretStr(database_urls[0]), statement_timeout_ms=statement, lock_timeout_ms=lock
    )
    svc = AgentService(settings)
    try:
        with checked_connection(database_urls[1], owner=True, test_only=True) as owner:
            owner.execute("LOCK TABLE business.orders IN ACCESS EXCLUSIVE MODE")
            started = time.monotonic()
            with pytest.raises(AgentError) as exc:
                svc.executor.execute("SELECT count(*) FROM business.orders")
            assert exc.value.kind == ErrorKind.SQL_TIMEOUT
            assert time.monotonic() - started < 2
        assert svc.executor.execute("SELECT count(*) FROM business.orders")["rows"] == [[500]]
    finally:
        svc.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    "override,sql",
    [
        ({"max_rows": 5}, "SELECT id FROM business.orders"),
        ({"max_bytes": 100}, "SELECT name FROM business.customers LIMIT 10"),
    ],
)
def test_output_budgets(database_urls, override, sql):
    svc = AgentService(Settings(database_url=SecretStr(database_urls[0]), **override))
    try:
        with pytest.raises(AgentError) as exc:
            svc.executor.execute(sql)
        assert exc.value.kind == ErrorKind.SQL_EXECUTION_ERROR
    finally:
        svc.close()


@pytest.mark.integration
def test_complexity_and_plan_budgets(secure):
    with pytest.raises(AgentError):
        secure.executor.execute(
            "SELECT id FROM business.orders WHERE " + " OR ".join(f"id={n}" for n in range(200))
        )
    with pytest.raises(AgentError) as exc:
        secure.executor.execute(
            "SELECT count(*) FROM business.orders a JOIN business.orders b ON a.id<>b.id JOIN business.orders c ON b.id<>c.id"
        )
    assert exc.value.kind == ErrorKind.SQL_VALIDATION_ERROR


@pytest.mark.integration
def test_unknown_column_and_ambiguous_column(secure):
    for sql in [
        "SELECT unknown FROM business.orders",
        "SELECT id FROM business.orders o JOIN business.customers c ON o.customer_id=c.id",
    ]:
        with pytest.raises(AgentError) as exc:
            secure.executor.execute(sql)
        assert exc.value.kind == ErrorKind.SCHEMA_NOT_FOUND
        assert exc.value.retryable


@pytest.mark.parametrize(
    "exception,kind,retry",
    [
        (psycopg.errors.SyntaxError(), "SQL_SYNTAX_ERROR", True),
        (psycopg.errors.InsufficientPrivilege(), "SQL_PERMISSION_DENIED", False),
        (psycopg.errors.QueryCanceled(), "SQL_TIMEOUT", False),
        (psycopg.errors.UndefinedColumn(), "SCHEMA_NOT_FOUND", True),
        (psycopg.errors.DivisionByZero(), "SQL_EXECUTION_ERROR", False),
    ],
)
def test_failure_classes(exception, kind, retry):
    result = classify_db_error(exception)
    assert result.kind.value == kind and result.retryable == retry
