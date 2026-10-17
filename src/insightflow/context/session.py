import time
from dataclasses import dataclass, field
from insightflow.database.errors import AgentError, ErrorKind


@dataclass
class Session:
    constraints: dict = field(default_factory=dict)
    history: list = field(default_factory=list)
    touched: float = field(default_factory=time.monotonic)


class SessionStore:
    """Single-process memory only. Caller serializes access under service lock."""

    def __init__(self, max_turns=4, capacity=128, ttl=1800):
        self.max_turns = max_turns
        self.capacity = capacity
        self.ttl = ttl
        self.sessions = {}

    def get(self, key):
        now = time.monotonic()
        for stale in [k for k, v in self.sessions.items() if now - v.touched > self.ttl]:
            del self.sessions[stale]
        if key not in self.sessions:
            if len(self.sessions) >= self.capacity:
                raise AgentError(ErrorKind.BUDGET_EXHAUSTED, "本地会话容量已满，请稍后重试。")
            self.sessions[key] = Session()
        self.sessions[key].touched = now
        return self.sessions[key]

    def record(self, session, question, result):
        if result.get("error") is None and result.get("query_result"):
            session.constraints = dict(result["plan"])
            session.history.append({"question": question, "answer": result["final_answer"]["answer"][:2048]})
            session.history = session.history[-self.max_turns :] if self.max_turns else []
