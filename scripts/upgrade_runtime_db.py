"""Local administrator setup: add ONLY a restricted runtime role, apply additive migrations.
Does not seed, truncate, drop or overwrite existing business rows.
"""

from pathlib import Path
import json
import os
import secrets
import subprocess
import psycopg
from psycopg import sql
from dotenv import dotenv_values, set_key

ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.geteuid() != 0:
        raise SystemExit("Administrator required for isolated runtime role provisioning")
    env = ROOT / ".env"
    original = env.stat()
    values = dotenv_values(env)
    password = values.get("INSIGHTFLOW_RUNTIME_PASSWORD") or secrets.token_urlsafe(32)
    # Connect as cluster admin using peer identity; never alter global authentication settings.
    role = "insightflow_runtime"
    encoded = sql.Literal(password).as_string()
    statement = f"DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='{role}') THEN CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {encoded}; END IF; END $$;"
    completed = subprocess.run(
        ["/usr/sbin/runuser", "-u", "postgres", "--", "psql", "-v", "ON_ERROR_STOP=1", "-q"],
        input=statement,
        text=True,
        capture_output=True,
    )
    if completed.returncode:
        raise SystemExit("Runtime role provisioning failed (credentials redacted)")
    for prefix, name in [("", "insightflow_dev"), ("TEST_", "insightflow_test")]:
        owner = values["INSIGHTFLOW_" + prefix + "ADMIN_DATABASE_URL"]
        with psycopg.connect(owner) as c:
            c.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(name), sql.Identifier(role)
                )
            )
        from migrate_v2 import migrate

        migrate(owner)
        # Preserve the established host/port; no password is displayed.
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(owner)
        params.update(user=role, password=password)
        runtime = make_conninfo(**params)
        key = "INSIGHTFLOW_V2_" + ("TEST_RUNTIME_URL" if prefix else "RUNTIME_URL")
        set_key(str(env), key, runtime, quote_mode="always")
    set_key(str(env), "INSIGHTFLOW_RUNTIME_PASSWORD", password, quote_mode="always")
    if not values.get("INSIGHTFLOW_V2_AUTH_TOKENS"):
        set_key(
            str(env),
            "INSIGHTFLOW_V2_AUTH_TOKENS",
            json.dumps({secrets.token_urlsafe(32): "local-demo", secrets.token_urlsafe(32): "second-demo"}),
            quote_mode="always",
        )
    os.chmod(env, 0o600)
    os.chown(env, original.st_uid, original.st_gid)
    print(
        "Additive runtime migrations applied to dedicated dev/test databases; local secrets saved privately."
    )


if __name__ == "__main__":
    main()
