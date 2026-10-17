from threading import RLock
from uuid import uuid4
from insightflow.agent.graph import build_graph
from insightflow.agent.nodes import Nodes
from insightflow.agent.tools import Tools
from insightflow.database.executor import ReadonlyExecutor
from insightflow.database.metadata import read_catalog
from insightflow.llm.mock import MockLLMProvider


class AgentService:
    def __init__(self, settings, provider=None):
        self.settings = settings
        self.provider = provider or MockLLMProvider()
        self.catalog = read_catalog(settings.database_url.get_secret_value())
        self.executor = ReadonlyExecutor(settings, self.catalog)
        self.tools = Tools(self.catalog, self.executor)
        self.graph = build_graph(Nodes(self.provider, self.tools, settings))
        self.lock = RLock()
        from insightflow.context.session import SessionStore

        self.sessions = SessionStore(settings.max_history_turns)

    def run(self, question, session_id="demo", previous=None):
        with self.lock:
            session = self.sessions.get(session_id)
            result = self.graph.invoke(
                {
                    "question": question,
                    "session_id": session_id,
                    "request_id": str(uuid4()),
                    "conversation_context": previous if previous is not None else dict(session.constraints),
                    "history": list(session.history),
                    "retry_count": 0,
                    "trace": [],
                    "error": None,
                    "model_calls": 0,
                },
                {"recursion_limit": 30},
            )
            result["usage"] = self.provider.usage()
            self.sessions.record(session, question, result)
            return result

    def close(self):
        self.executor.close()
