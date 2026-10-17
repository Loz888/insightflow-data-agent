from insightflow.database.errors import AgentError, ErrorKind


class Nodes:
    def __init__(self, provider, tools, settings):
        self.provider = provider
        self.tools = tools
        self.settings = settings

    def call(self, state, name, function):
        trace = state.get("trace", []) + [name]
        try:
            return {"trace": trace, "error": None, **function()}
        except AgentError as exc:
            return {"trace": trace, "error": exc.as_dict(), "retryable": exc.retryable}

    def understand(self, s):
        def run():
            plan = self.provider.understand(s["question"], s.get("conversation_context", {}))
            return {"plan": plan.model_dump(), "model_calls": s.get("model_calls", 0) + 1}

        return self.call(s, "UnderstandQuestion", run)

    def select(self, s):
        from insightflow.llm.base import Plan
        from insightflow.retrieval.retriever import SchemaRetriever

        def run():
            result = self.tools.measured(
                s,
                "SelectSchema",
                "retrieve_schema",
                lambda: SchemaRetriever(self.tools.catalog, self.settings.max_schema_items).retrieve(
                    s["question"], Plan.model_validate(s["plan"])
                ),
            )
            for name in result["retrieved_tables"]:
                self.tools.measured(
                    s, "SelectSchema", "get_table_schema", lambda n=name: self.tools.get_table_schema(n)
                )
            self.tools.measured(
                s,
                "SelectSchema",
                "get_metric_definition",
                lambda: self.tools.get_metric_definition(s["plan"]["metric"]),
            )
            return {"selected_tables": result["retrieved_tables"], "retrieved_context": result}

        return self.call(s, "SelectSchema", run)

    def generate(self, s):
        from insightflow.llm.base import Plan
        from insightflow.context.manager import ContextManager

        def run():
            context = ContextManager(self.settings).build(
                s["question"],
                Plan.model_validate(s["plan"]),
                s["retrieved_context"],
                s.get("history", []),
                s.get("feedback"),
            )
            generated = self.provider.generate(
                Plan.model_validate(s["plan"]), context["text"], s.get("feedback")
            )
            return {
                "generated_sql": generated.sql,
                "model_calls": s.get("model_calls", 0) + 1,
                "context_budget": context,
            }

        return self.call(s, "GenerateSQL", run)

    def validate(self, s):
        def run():
            checked = self.tools.executor.validator.validate(s["generated_sql"])
            return {"validation_result": {"valid": True, "tables": list(checked.tables)}}

        return self.call(s, "ValidateSQL", run)

    def execute(self, s):
        def run():
            rows = self.tools.measured(
                s,
                "ExecuteSQL",
                "execute_readonly_sql",
                lambda: self.tools.execute_readonly_sql(s["generated_sql"]),
            )
            return {"query_result": rows}

        return self.call(s, "ExecuteSQL", run)

    def classify(self, s):
        count = s.get("retry_count", 0)
        if s.get("retryable") and count < self.settings.max_sql_retries:
            return {
                "retry_count": count + 1,
                "feedback": s["error"]["message"],
                "error": None,
                "retryable": False,
                "trace": s["trace"] + ["ClassifyFailure"],
            }
        if s.get("retryable"):
            return {
                "error": {"kind": ErrorKind.BUDGET_EXHAUSTED.value, "message": "SQL 修正次数已耗尽。"},
                "retryable": False,
                "trace": s["trace"] + ["ClassifyFailure"],
            }
        return {"retryable": False, "trace": s["trace"] + ["ClassifyFailure"]}

    def answer(self, s):
        trace = s.get("trace", []) + ["GenerateAnswer"]
        if s.get("error") or not s.get("query_result"):
            return {
                "trace": trace,
                "final_answer": {
                    "answer": "证据不足：" + s.get("error", {}).get("message", "没有查询结果。"),
                    "sql": s.get("generated_sql", ""),
                    "tables_used": [],
                    "evidence": {},
                    "limitations": ["未获得可信查询证据。"],
                },
            }
        result = s["query_result"]
        limitations = [
            "仅描述固定合成数据；观察性比较不能证明因果关系。",
            "退款按订单日期归属；币种 CNY，时间 UTC。",
        ]
        if not result["rows"] or any(v is None for row in result["rows"] for v in row):
            answer = "证据不足：查询为空或分母为零。"
            limitations.append("空结果或 NULL 不当作零。")
        else:
            import json

            answer = "查询结果：" + json.dumps(
                {"columns": result["columns"], "rows": result["rows"]}, ensure_ascii=False
            )
        return {
            "trace": trace,
            "final_answer": {
                "answer": answer,
                "sql": s["generated_sql"],
                "tables_used": s["validation_result"]["tables"],
                "evidence": result,
                "limitations": limitations,
            },
        }
