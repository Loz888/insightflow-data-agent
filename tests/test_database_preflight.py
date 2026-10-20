"""The expanded-schema preflight must still reject additional reader grants."""

import importlib.util
from pathlib import Path
from uuid import uuid4
import pytest
from psycopg import sql
from insightflow.database.connection import checked_connection

pytestmark = pytest.mark.integration


def test_v2_preflight_preserves_core_and_rejects_unexpected_grants(database_urls):
    reader, owner = database_urls
    path = Path(__file__).resolve().parents[1] / "scripts/check_database.py"
    spec = importlib.util.spec_from_file_location("database_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.check(reader, "v2")
    assert result["counts"] == module.CORE_COUNTS and len(result["authorized_tables"]) == 10
    with checked_connection(reader, test_only=True) as conn:
        reader_role = conn.execute("SELECT current_user").fetchone()[0]
    table = "preflight_unexpected_" + uuid4().hex
    with checked_connection(owner, owner=True, test_only=True) as conn:
        conn.execute(sql.SQL("CREATE TABLE business.{}(id integer)").format(sql.Identifier(table)))
        conn.execute(
            sql.SQL("GRANT SELECT ON business.{} TO {}").format(
                sql.Identifier(table), sql.Identifier(reader_role)
            )
        )
    try:
        with pytest.raises(AssertionError, match="unexpected business table access"):
            module.check(reader, "v2")
    finally:
        with checked_connection(owner, owner=True, test_only=True) as conn:
            conn.execute(sql.SQL("DROP TABLE business.{}").format(sql.Identifier(table)))
    assert module.check(reader, "v2")["permissions"] == "PASS"
