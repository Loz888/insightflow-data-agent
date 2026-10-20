from decimal import Decimal
from pydantic import SecretStr
import pytest
from insightflow.config import Settings
from insightflow.database.executor import ReadonlyExecutor
from insightflow.database.metadata import read_catalog
from insightflow.evaluation.scorer import equivalent, column_kind

pytestmark = pytest.mark.integration


def test_database_column_types_survive_decimal_json_serialization(database_urls):
    reader, _ = database_urls
    executor = ReadonlyExecutor(Settings(database_url=SecretStr(reader)), read_catalog(reader))
    try:
        actual = executor.execute(
            "SELECT category AS dimension, price AS value FROM business.products ORDER BY id LIMIT 2"
        )
        assert [column_kind(t) for t in actual["column_types"]] == ["text", "number"]
        assert all(isinstance(row[1], str) for row in actual["rows"])
        expected = {
            "columns": ["dimension", "value"],
            "column_types": ["text", "numeric"],
            "rows": [[row[0], str(Decimal(row[1]) + Decimal("0.000000001"))] for row in actual["rows"]],
        }
        assert equivalent(actual, expected, ordered=True)
        expected["rows"][0][0] += "-wrong"
        assert not equivalent(actual, expected, ordered=True)
    finally:
        executor.close()
