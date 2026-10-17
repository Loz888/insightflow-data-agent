from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    question: str
    session_id: str
    request_id: str
    conversation_context: dict[str, Any]
    selected_tables: list[str]
    retrieved_context: dict[str, Any]
    generated_sql: str
    validation_result: dict[str, Any]
    query_result: dict[str, Any]
    final_answer: dict[str, Any]
    error: dict[str, str] | None
    retry_count: int
    trace: list[str]
    model_calls: int

    plan: dict[str, Any]
    retryable: bool
    feedback: str | None
    usage: dict[str, Any]
