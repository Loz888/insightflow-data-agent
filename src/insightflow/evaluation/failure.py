def failure_category(
    error_kind, *, metric_correct=True, context_correct=True, grounded=True, has_history=False
):
    if error_kind and error_kind.startswith("MODEL_"):
        return "Model API Failure"
    if error_kind == "SCHEMA_RETRIEVAL_ERROR":
        return "Schema Selection Error"
    if has_history and error_kind == "CLARIFICATION_REQUIRED":
        return "Context Resolution Error"
    if not metric_correct:
        return "Metric Interpretation Error"
    if not context_correct:
        return "Context Resolution Error"
    if error_kind == "SQL_VALIDATION_ERROR":
        return "SQL Validation Failure"
    if error_kind in ("SQL_SYNTAX_ERROR", "SCHEMA_NOT_FOUND", "BUDGET_EXHAUSTED"):
        return "SQL Generation Error"
    if error_kind and error_kind.startswith("SQL_"):
        return "SQL Execution Failure"
    if not grounded:
        return "Answer Grounding Error"
    return "SQL Generation Error"
