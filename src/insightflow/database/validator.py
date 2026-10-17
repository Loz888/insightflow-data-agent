"""Default-deny PostgreSQL AST policy; database permissions remain independent."""

from dataclasses import dataclass
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, OptimizeError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope
from insightflow.database.errors import AgentError, ErrorKind

# Every admitted syntax node must be intentional. Unknown/new syntax is rejected.
ALLOWED = set(
    """Select With CTE Subquery From Table Identifier TableAlias Column Star Alias
Join Where Group Having Order Ordered Limit Offset Literal Null Boolean Paren
And Or Not EQ NEQ GT GTE LT LTE Is In Between Add Sub Mul Div Neg
Count Sum Avg Min Max Coalesce Nullif Round Cast DataType DataTypeParam
Distinct Filter Case If When DateTrunc TimestampTrunc TimeToStr AtTimeZone""".split()
)
FUNCTIONS = {
    "And",
    "Or",
    "Case",
    "If",
    "Count",
    "Sum",
    "Avg",
    "Min",
    "Max",
    "Coalesce",
    "Nullif",
    "Round",
    "Cast",
    "DateTrunc",
    "TimestampTrunc",
    "TimeToStr",
}
TYPES = {"INT", "BIGINT", "DECIMAL", "NUMERIC", "DATE", "TIMESTAMP", "TIMESTAMPTZ", "TEXT", "VARCHAR"}


@dataclass(frozen=True)
class ValidatedSQL:
    sql: str
    tables: tuple[str, ...]


class SQLValidator:
    def __init__(self, catalog):
        self.catalog = catalog

    def validate(self, sql: str) -> ValidatedSQL:
        def reject(message):
            raise AgentError(ErrorKind.SQL_VALIDATION_ERROR, message)

        if not isinstance(sql, str) or not 1 <= len(sql) <= 8000:
            reject("SQL 长度超出允许范围。")
        try:
            statements = sqlglot.parse(sql, read="postgres")
        except ParseError:
            raise AgentError(
                ErrorKind.SQL_SYNTAX_ERROR, "SQL 解析失败，可按已检索字段修正。", retryable=True
            ) from None
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            reject("仅允许单条受支持 SELECT 查询。")
        tree = statements[0]
        nodes = list(tree.walk())
        if len(nodes) > 450 or any(n.depth > 30 for n in nodes):
            reject("查询 AST 超出复杂度预算。")
        for node in nodes:
            name = type(node).__name__
            if name not in ALLOWED:
                reject("不支持或危险的 SQL 结构：" + name)
            if isinstance(node, exp.Func) and name not in FUNCTIONS:
                reject("函数不在允许列表中。")
            if isinstance(node, exp.Literal) and len(str(node.this)) > 1024:
                reject("SQL 常量过大。")
            if isinstance(node, exp.Cast):
                if getattr(node.to.this, "value", None) not in TYPES:
                    reject("类型转换不在允许列表中。")
            if isinstance(node, exp.Join) and (
                not node.args.get("on") or node.args.get("method") or node.args.get("kind") == "CROSS"
            ):
                reject("禁止无条件连接或不受控连接语法。")
            if isinstance(node, exp.Join) and node.args.get("on") is not None:
                if not list(node.args["on"].find_all(exp.Column)):
                    reject("JOIN 条件必须引用受检字段。")
            if isinstance(node, exp.Table) and (node.catalog or node.args.get("pivots")):
                reject("禁止跨数据库和动态表语法。")
        if len(list(tree.find_all(exp.Join))) > 6:
            reject("连接数量超出预算。")
        ctes = [c.alias for c in tree.find_all(exp.CTE)]
        if len(ctes) != len(set(ctes)) or any(c in self.catalog for c in ctes):
            reject("CTE 名称冲突。")
        tables = set()
        for scope in traverse_scope(tree):
            for source in scope.sources.values():
                if isinstance(source, exp.Table):
                    if source.db not in ("", "business"):
                        reject("未授权 Schema。")
                    if source.name not in self.catalog:
                        reject("未授权业务表。")
                    tables.add(source.name)
                    source.set("db", exp.to_identifier("business"))
        if not tables:
            reject("查询必须读取允许的业务表。")
        try:
            schema = {
                "business": {
                    name: {c: kind for c, kind in meta.columns.items()} for name, meta in self.catalog.items()
                }
            }
            qualified = qualify(tree, dialect="postgres", schema=schema, validate_qualify_columns=True)
        except (OptimizeError, sqlglot.errors.SchemaError):
            raise AgentError(
                ErrorKind.SCHEMA_NOT_FOUND, "字段不存在或引用有歧义，请使用已检索 Schema。", retryable=True
            ) from None
        # Resolve overloaded ordinary functions explicitly in pg_catalog.
        # search_path alone is insufficient: an exact business overload could
        # otherwise beat a built-in requiring implicit numeric conversion.
        builtin_calls = {
            "Count",
            "Sum",
            "Avg",
            "Min",
            "Max",
            "Round",
            "DateTrunc",
            "TimestampTrunc",
            "TimeToStr",
        }
        for function in reversed(list(qualified.find_all(exp.Func))):
            if type(function).__name__ in builtin_calls:
                function.replace(exp.Dot(this=exp.to_identifier("pg_catalog"), expression=function.copy()))
        return ValidatedSQL(qualified.sql(dialect="postgres"), tuple(sorted(tables)))
