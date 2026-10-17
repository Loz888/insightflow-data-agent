"""Create two NEW isolated snapshots; never reset original dev/test business data."""

from pathlib import Path
import os
import subprocess
import json
from dotenv import dotenv_values, set_key
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from insightflow.database.connection import checked_connection
from seed_data import seed

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.geteuid() != 0:
        raise SystemExit("Explicit local administrator setup required")
    path = ROOT / ".env"
    original = path.stat()
    d = dotenv_values(path)
    report = []
    for n in (101, 202):
        name = "insightflow_v2_seed" + str(n)
        exists = subprocess.run(
            [
                "/usr/sbin/runuser",
                "-u",
                "postgres",
                "--",
                "psql",
                "-tAc",
                "SELECT 1 FROM pg_database WHERE datname='" + name + "'",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        params = conninfo_to_dict(d["INSIGHTFLOW_ADMIN_DATABASE_URL"])
        params["dbname"] = name
        owner = make_conninfo(**params)
        if not exists:
            subprocess.run(
                ["/usr/sbin/runuser", "-u", "postgres", "--", "createdb", "-O", "insightflow_owner", name],
                check=True,
            )
            with checked_connection(owner, owner=True) as c:
                for migration in sorted((ROOT / "migrations").glob("00[1-4]*.sql")):
                    c.execute(migration.read_text())
            counts = seed(owner, random_seed=n)
            with checked_connection(owner, owner=True) as c:
                c.execute((ROOT / "migrations/007_v2_business_extensions.sql").read_text())
        else:
            with checked_connection(owner, owner=True) as c:
                counts = {
                    t: c.execute("SELECT count(*) FROM business." + t).fetchone()[0]
                    for t in ("customers", "products", "orders", "order_items", "refunds")
                }
        with checked_connection(owner, owner=True) as c:
            for extension in sorted((ROOT / "migrations").glob("00[7-8]*.sql")):
                c.execute(extension.read_text())
        reader = conninfo_to_dict(d["INSIGHTFLOW_DATABASE_URL"])
        reader["dbname"] = name
        set_key(
            str(path), "INSIGHTFLOW_V2_SEED" + str(n) + "_URL", make_conninfo(**reader), quote_mode="always"
        )
        report.append(
            {
                "data_version": "v2-seed" + str(n),
                "seed": n,
                "counts": counts,
                "new_snapshot": not bool(exists),
            }
        )
    os.chmod(path, 0o600)
    os.chown(path, original.st_uid, original.st_gid)
    target = ROOT / "evaldata/v2"
    target.mkdir(exist_ok=True, parents=True)
    (target / "snapshots.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Independent seed101/202 snapshots ready; original data unchanged.")


if __name__ == "__main__":
    main()
