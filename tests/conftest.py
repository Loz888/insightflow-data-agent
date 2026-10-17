import os
from pathlib import Path
import pytest
from dotenv import dotenv_values


@pytest.fixture(scope="session")
def database_urls():
    values = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
    reader = os.environ.get("INSIGHTFLOW_TEST_DATABASE_URL") or values.get("INSIGHTFLOW_TEST_DATABASE_URL")
    owner = os.environ.get("INSIGHTFLOW_TEST_ADMIN_DATABASE_URL") or values.get(
        "INSIGHTFLOW_TEST_ADMIN_DATABASE_URL"
    )
    if not reader or not owner:
        pytest.fail("Dedicated InsightFlow TEST database configuration required; no SKIP")
    from insightflow.database.connection import checked_connection

    with checked_connection(reader, test_only=True):
        pass
    with checked_connection(owner, owner=True, test_only=True):
        pass
    return reader, owner
