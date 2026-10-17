from pydantic import BaseModel
from insightflow.database.connection import checked_connection

TABLES = ("customers", "products", "orders", "order_items", "refunds")


class TableMetadata(BaseModel):
    table_name: str
    columns: dict[str, str]
    foreign_keys: list[dict[str, str]]


def read_catalog(dsn: str) -> dict[str, TableMetadata]:
    with checked_connection(dsn) as conn:
        rows = conn.execute(
            "SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='business' ORDER BY table_name,ordinal_position"
        ).fetchall()
        result = {}
        for table, column, kind in rows:
            if table in TABLES:
                result.setdefault(
                    table, TableMetadata(table_name=table, columns={}, foreign_keys=[])
                ).columns[column] = kind
        relations = conn.execute("""
            SELECT s.relname,a.attname,t.relname,b.attname
            FROM pg_constraint c
            JOIN pg_class s ON s.oid=c.conrelid JOIN pg_namespace n ON n.oid=s.relnamespace
            JOIN pg_class t ON t.oid=c.confrelid
            JOIN pg_attribute a ON a.attrelid=s.oid AND a.attnum=c.conkey[1]
            JOIN pg_attribute b ON b.attrelid=t.oid AND b.attnum=c.confkey[1]
            WHERE c.contype='f' AND n.nspname='business'
        """).fetchall()
        for source, column, target, target_column in relations:
            if source in result:
                result[source].foreign_keys.append(
                    {"column": column, "target_table": target, "target_column": target_column}
                )
        if set(result) != set(TABLES):
            raise ValueError("Business schema incomplete")
        return result
