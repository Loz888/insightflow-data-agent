"""Small, allowlisted request/node/tool events; never log question, SQL or rows."""

import functools
import hashlib
import json
import logging
import time

log = logging.getLogger("insightflow.trace")
STAGES = {
    "UnderstandQuestion": "understanding_duration_ms",
    "SelectSchema": "retrieval_duration_ms",
    "GenerateSQL": "generation_node_duration_ms",
    "ValidateSQL": "validation_duration_ms",
    "ExecuteSQL": "sql_duration_ms",
    "GenerateAnswer": "answer_duration_ms",
    "ClassifyFailure": "classification_duration_ms",
}


def event(state, node, duration, error=None, tool=None, retries=None):
    model = state.get("model_name", "mock")
    if model not in ("mock", "deepseek-flash", "deepseek-v4-pro"):
        model = "custom"
    return {
        "run_id": state["request_id"],
        "request_id": state["request_id"],
        "session_id": "sha256:" + hashlib.sha256(state["session_id"].encode()).hexdigest()[:16],
        "model_name": model,
        "node_name": node,
        "tool_name": tool,
        "duration_ms": round(duration, 3),
        "error_kind": error,
        "retry_count": retries if retries is not None else state.get("retry_count", 0),
    }


def emit(value):
    log.info(json.dumps(value, ensure_ascii=False))


def observed_node(name):
    def decorate(function):
        @functools.wraps(function)
        def wrapped(self, state):
            started = time.perf_counter()
            result = function(self, state)
            elapsed = (time.perf_counter() - started) * 1000
            error = result.get("error", state.get("error"))
            item = event(
                state,
                name,
                elapsed,
                error.get("kind") if error else None,
                retries=result.get("retry_count", state.get("retry_count", 0)),
            )
            timings = dict(state.get("timings", {}))
            key = STAGES[name]
            timings[key] = timings.get(key, 0) + elapsed
            for key, value in result.pop("_timing_additions", {}).items():
                timings[key] = timings.get(key, 0) + value
            result["timings"] = timings
            result["node_events"] = state.get("node_events", []) + [item]
            emit(item)
            return result

        return wrapped

    return decorate
