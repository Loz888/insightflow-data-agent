import psycopg
from psycopg.conninfo import conninfo_to_dict

DATABASES = {"insightflow_dev", "insightflow_test"}


def checked_connection(dsn: str, *, owner: bool = False, test_only: bool = False):
    params = conninfo_to_dict(dsn)
    allowed = {"insightflow_test"} if test_only else DATABASES
    if params.get("dbname") not in allowed:
        raise ValueError("Only dedicated InsightFlow databases are allowed")
    expected = "insightflow_owner" if owner else "insightflow_reader"
    if params.get("user") != expected:
        raise ValueError("Wrong database role")
    conn = psycopg.connect(dsn, connect_timeout=3)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT current_database(),current_user,r.rolsuper,r.rolcreatedb,r.rolcreaterole FROM pg_roles r WHERE rolname=current_user"
        )
        row = cur.fetchone()
        cur.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()")
        dbowner = cur.fetchone()[0]
        if row[0] not in allowed or row[1] != expected or any(row[2:]) or (not owner and dbowner == expected):
            conn.close()
            raise ValueError("Unsafe actual database identity")
    conn.commit()
    return conn
