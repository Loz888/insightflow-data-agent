"""Only fresh ephemeral CI cluster; grant runtime and seed independently versioned snapshots."""

import os
from pathlib import Path
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from insightflow.database.connection import checked_connection
from migrate_v2 import migrate
from seed_data import seed

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Ephemeral CI only")
r = Path(__file__).resolve().parents[1]
settings = {}
for label in ("", "TEST_"):
    owner = os.environ["INSIGHTFLOW_" + label + "ADMIN_DATABASE_URL"]
    migrate(owner)
    params = conninfo_to_dict(owner)
    params.update(user="insightflow_runtime", password=os.environ["INSIGHTFLOW_CI_RUNTIME_PASSWORD"])
    settings["INSIGHTFLOW_V2_" + ("TEST_RUNTIME_URL" if label else "RUNTIME_URL")] = make_conninfo(**params)
for n in (101, 202):
    owner = conninfo_to_dict(os.environ["INSIGHTFLOW_TEST_ADMIN_DATABASE_URL"])
    owner["dbname"] = "insightflow_v2_seed" + str(n)
    owner = make_conninfo(**owner)
    with checked_connection(owner, owner=True) as c:
        for path in sorted((r / "migrations").glob("00[1-4]*.sql")):
            c.execute(path.read_text())
        if c.execute("SELECT count(*) FROM business.orders").fetchone()[0]:
            raise SystemExit("Refuse snapshot reset")
    seed(owner, random_seed=n)
    with checked_connection(owner, owner=True) as c:
        for extension in sorted((r / "migrations").glob("00[7-8]*.sql")):
            c.execute(extension.read_text())
    reader = conninfo_to_dict(os.environ["INSIGHTFLOW_TEST_DATABASE_URL"])
    reader["dbname"] = "insightflow_v2_seed" + str(n)
    settings["INSIGHTFLOW_V2_SEED" + str(n) + "_URL"] = make_conninfo(**reader)
settings["INSIGHTFLOW_V2_AUTH_TOKENS"] = '{"ci-ephemeral-long-auth-token-only":"ci"}'
with open(os.environ["GITHUB_ENV"], "a") as f:
    for key, value in settings.items():
        f.write(key + "=" + value + "\n")
print("Ephemeral runtime permissions and independent seed snapshots ready.")
