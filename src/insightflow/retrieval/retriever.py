from insightflow.database.errors import AgentError, ErrorKind
from insightflow.retrieval.glossary import METRIC_TABLES
from insightflow.database.metadata import TABLES
from insightflow.retrieval.schema_catalog import DESCRIPTIONS
from insightflow.retrieval.glossary import METRICS


class SchemaRetriever:
    def __init__(self, catalog, max_items=5):
        self.catalog = {name: table for name, table in catalog.items() if name in TABLES}
        self.max_items = max_items

    def retrieve(self, question, plan):
        if plan.metric not in METRICS:
            raise AgentError(ErrorKind.CLARIFICATION_REQUIRED, "业务指标没有受信任定义。")
        required = set(METRIC_TABLES[plan.metric])
        if plan.region or plan.group in ("region", "customer"):
            required |= {"orders", "customers"}
        if plan.group in ("category", "product"):
            required.add("products")
            if "orders" in required:
                required.add("order_items")
        # Join closure follows trusted FK metadata, never a model-created relation.
        connected = set(required)
        if len(required) > 1:
            graph = {t: set() for t in self.catalog}
            for name, table in self.catalog.items():
                for fk in table.foreign_keys:
                    graph[name].add(fk["target_table"])
                    graph[fk["target_table"]].add(name)
            start = sorted(required)[0]
            for target in required:
                queue = [(start, [start])]
                seen = set()
                while queue:
                    current, path = queue.pop(0)
                    if current == target:
                        connected.update(path)
                        break
                    if current in seen:
                        continue
                    seen.add(current)
                    queue.extend((n, path + [n]) for n in sorted(graph[current]) if n not in seen)
        scores = {}
        for name, table in self.catalog.items():
            tokens = [name, *DESCRIPTIONS[name].split(), *table.columns]
            scores[name] = 100 * int(name in connected) + sum(
                1 for token in tokens if token.lower() in question.lower()
            )
        ranking = sorted(scores, key=lambda n: (-scores[n], n))
        selected = [n for n in ranking if n in connected]
        if len(selected) > self.max_items:
            raise AgentError(
                ErrorKind.BUDGET_EXHAUSTED, "Schema 预算无法容纳完整指标/JOIN，不能删除关键关系。"
            )
        return {
            "retrieved_tables": selected,
            "retrieved_columns": [f"{n}.{c}" for n in selected for c in self.catalog[n].columns],
            "retrieved_metrics": {plan.metric: METRICS[plan.metric]},
            "retrieval_scores": {n: scores[n] for n in ranking},
            "schemas": [
                {
                    **self.catalog[n].model_dump(),
                    "description": DESCRIPTIONS[n],
                    "column_descriptions": {
                        c: f"{n}.{c}，类型 {kind}；业务含义以指标术语表为准。"
                        for c, kind in self.catalog[n].columns.items()
                    },
                }
                for n in selected
            ],
        }
