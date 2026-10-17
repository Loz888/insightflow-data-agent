from enum import StrEnum


class ErrorKind(StrEnum):
    SQL_SYNTAX_ERROR = "SQL_SYNTAX_ERROR"
    SQL_VALIDATION_ERROR = "SQL_VALIDATION_ERROR"
    SQL_PERMISSION_DENIED = "SQL_PERMISSION_DENIED"
    SQL_TIMEOUT = "SQL_TIMEOUT"
    SQL_EXECUTION_ERROR = "SQL_EXECUTION_ERROR"
    SCHEMA_NOT_FOUND = "SCHEMA_NOT_FOUND"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"


class AgentError(Exception):
    def __init__(self, kind, message, *, retryable=False):
        super().__init__(message)
        self.kind = ErrorKind(kind)
        self.message = message
        self.retryable = retryable

    def as_dict(self):
        return {"kind": self.kind.value, "message": self.message}


def classify_db_error(exc):
    code = getattr(exc, "sqlstate", None)
    if code == "42501":
        return AgentError(ErrorKind.SQL_PERMISSION_DENIED, "查询账号没有所需权限。")
    if code in ("57014", "55P03"):
        return AgentError(ErrorKind.SQL_TIMEOUT, "查询超出时间或锁等待预算。")
    if code == "42601":
        return AgentError(ErrorKind.SQL_SYNTAX_ERROR, "数据库无法解析 SQL。", retryable=True)
    if code == "42703":
        return AgentError(ErrorKind.SCHEMA_NOT_FOUND, "字段不存在，请根据检索元数据修正。", retryable=True)
    return AgentError(ErrorKind.SQL_EXECUTION_ERROR, "查询执行失败；未返回未经验证的数据。")
