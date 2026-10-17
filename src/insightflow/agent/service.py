from threading import RLock
from uuid import uuid4
from insightflow.agent.graph import build_graph
from insightflow.agent.nodes import Nodes
from insightflow.agent.tools import Tools
from insightflow.database.executor import ReadonlyExecutor
from insightflow.retrieval.schema_catalog import SchemaCatalog
from insightflow.llm.mock import MockLLMProvider


class AgentService:
    def __init__(self, settings, provider=None):
        self.settings = settings
        if provider is not None:
            self.provider = provider
        elif settings.mode == "deepseek":
            from insightflow.llm.deepseek import DeepSeekLLMProvider

            self.provider = DeepSeekLLMProvider()
        else:
            self.provider = MockLLMProvider()
        self.schema_catalog = SchemaCatalog(settings.database_url.get_secret_value())
        self.catalog = self.schema_catalog.tables
        self.executor = ReadonlyExecutor(settings, self.catalog)
        self.tools = Tools(self.catalog, self.executor)
        self.graph = build_graph(Nodes(self.provider, self.tools, settings))
        self.lock = RLock()
        from insightflow.context.session import SessionStore

        self.sessions = SessionStore(settings.max_history_turns)

    def run(self, question, session_id="demo", previous=None, cancellation=None):
        from insightflow.agent.cancellation import Cancellation, CURRENT_CANCELLATION
        from insightflow.database.errors import AgentError, ErrorKind

        token = cancellation or Cancellation()
        while not self.lock.acquire(timeout=0.05):
            token.check()
        context = CURRENT_CANCELLATION.set(token)
        try:
            before_usage = self.provider.usage()
            try:
                session = self.sessions.get(session_id)
            except AgentError:
                raise
            except Exception:
                raise AgentError(ErrorKind.SESSION_STATE_ERROR, "本地会话状态不可用。") from None
            use_history = self.settings.experiment_mode in ("context_only", "full")
            token.check()
            result = self.graph.invoke(
                {
                    "question": question,
                    "session_id": session_id,
                    "request_id": str(uuid4()),
                    "conversation_context": (previous if previous is not None else dict(session.constraints))
                    if use_history
                    else {},
                    "history": list(session.history) if use_history else [],
                    "retry_count": 0,
                    "trace": [],
                    "error": None,
                    "model_calls": 0,
                },
                {"recursion_limit": 30},
            )
            result["usage"] = dict(self.provider.usage())
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                if result["usage"].get(key) is not None and before_usage.get(key) is not None:
                    result["usage"][key] -= before_usage[key]
            result["model_calls"] = sum(
                name in ("UnderstandQuestion", "GenerateSQL") for name in result["trace"]
            )
            if "api_calls" in result["usage"]:
                result["model_calls"] = result["usage"]["api_calls"] - before_usage["api_calls"]
            token.check()
            try:
                self.sessions.record(session, question, result)
            except Exception:
                raise AgentError(
                    ErrorKind.SESSION_STATE_ERROR, "会话保存失败，未返回本轮业务答案。"
                ) from None
            return result
        finally:
            CURRENT_CANCELLATION.reset(context)
            self.lock.release()

    def close(self):
        self.executor.close()
