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
        relations = [
            ("orders", "customer_id", "customers", "id"),
            ("order_items", "order_id", "orders", "id"),
            ("order_items", "product_id", "products", "id"),
            ("refunds", "order_id", "orders", "id"),
        ]
        for source, column, target, target_column in relations:
            if source in result:
                result[source].foreign_keys.append(
                    {"column": column, "target_table": target, "target_column": target_column}
                )
        if set(result) != set(TABLES):
            raise ValueError("Business schema incomplete")
        return result
