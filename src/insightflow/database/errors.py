from enum import StrEnum


class ErrorKind(StrEnum):
    SQL_SYNTAX_ERROR = "SQL_SYNTAX_ERROR"
    SQL_VALIDATION_ERROR = "SQL_VALIDATION_ERROR"
    SQL_PERMISSION_DENIED = "SQL_PERMISSION_DENIED"
    SQL_TIMEOUT = "SQL_TIMEOUT"
    SQL_EXECUTION_ERROR = "SQL_EXECUTION_ERROR"
    SQL_CONNECTION_FAILURE = "SQL_CONNECTION_FAILURE"
    SCHEMA_RETRIEVAL_ERROR = "SCHEMA_RETRIEVAL_ERROR"
    SESSION_STATE_ERROR = "SESSION_STATE_ERROR"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SCHEMA_NOT_FOUND = "SCHEMA_NOT_FOUND"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MODEL_AUTH_ERROR = "MODEL_AUTH_ERROR"
    MODEL_RATE_LIMIT = "MODEL_RATE_LIMIT"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_UPSTREAM_ERROR = "MODEL_UPSTREAM_ERROR"
    MODEL_INVALID_RESPONSE = "MODEL_INVALID_RESPONSE"
    MODEL_OUTPUT_TRUNCATED = "MODEL_OUTPUT_TRUNCATED"
    MODEL_BUDGET_EXHAUSTED = "MODEL_BUDGET_EXHAUSTED"


class AgentError(Exception):
    def __init__(self, kind, message, *, retryable=False):
        super().__init__(message)
        self.kind = ErrorKind(kind)
        self.message = message
        self.retryable = retryable

    def as_dict(self):
        return {"kind": self.kind.value, "message": self.message}


def classify_db_error(exc):
    import psycopg

    code = getattr(exc, "sqlstate", None)
    if (code and code.startswith("08")) or (isinstance(exc, psycopg.OperationalError) and code is None):
        return AgentError(ErrorKind.SQL_CONNECTION_FAILURE, "专用分析数据库连接失败。")
    if code == "42501":
        return AgentError(ErrorKind.SQL_PERMISSION_DENIED, "查询账号没有所需权限。")
    if code in ("57014", "55P03"):
        return AgentError(ErrorKind.SQL_TIMEOUT, "查询超出时间或锁等待预算。")
    if code == "42601":
        return AgentError(ErrorKind.SQL_SYNTAX_ERROR, "数据库无法解析 SQL。", retryable=True)
    if code == "42703":
        return AgentError(ErrorKind.SCHEMA_NOT_FOUND, "字段不存在，请根据检索元数据修正。", retryable=True)
    return AgentError(ErrorKind.SQL_EXECUTION_ERROR, "查询执行失败；未返回未经验证的数据。")
