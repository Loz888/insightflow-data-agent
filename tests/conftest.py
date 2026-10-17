import os
from pathlib import Path
import pytest
from dotenv import dotenv_values


class RedactedDSN(str):
    def __repr__(self):
        return "<InsightFlow test database DSN redacted>"


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
    return RedactedDSN(reader), RedactedDSN(owner)


def pytest_addoption(parser):
    parser.addoption("--evidence-json", default=None)


def pytest_collection_modifyitems(config, items):
    config._insightflow_groups = {
        item.nodeid: ("integration" if item.get_closest_marker("integration") else "unit") for item in items
    }


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    import json

    target = config.getoption("--evidence-json")
    if not target:
        return
    stats = terminalreporter.stats
    groups = getattr(config, "_insightflow_groups", {})
    passed = stats.get("passed", [])
    report = {
        "passed": len(passed),
        "failed": len(stats.get("failed", [])),
        "skipped": len(stats.get("skipped", [])),
        "errors": len(stats.get("error", [])),
        "unit_passed": sum(groups.get(r.nodeid) == "unit" for r in passed),
        "integration_passed": sum(groups.get(r.nodeid) == "integration" for r in passed),
    }
    Path(target).write_text(json.dumps(report, indent=2) + "\n")
