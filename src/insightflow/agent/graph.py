from langgraph.graph import END, START, StateGraph
from insightflow.agent.state import AgentState


def build_basic_graph():
    def understand(state):
        return {"trace": ["UnderstandQuestion"], "retry_count": 0}

    def finish(state):
        return {
            "trace": state["trace"] + ["GenerateAnswer"],
            "final_answer": {"answer": "基础工作流已运行，数据分析尚未接入。"},
        }

    graph = StateGraph(AgentState)
    graph.add_node("understand", understand)
    graph.add_node("finish", finish)
    graph.add_edge(START, "understand")
    graph.add_edge("understand", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


def build_graph(nodes):
    from insightflow.agent.routing import after_node, after_classify

    graph = StateGraph(AgentState)
    for name, method in [
        ("UnderstandQuestion", nodes.understand),
        ("SelectSchema", nodes.select),
        ("GenerateSQL", nodes.generate),
        ("ValidateSQL", nodes.validate),
        ("ExecuteSQL", nodes.execute),
        ("ClassifyFailure", nodes.classify),
        ("GenerateAnswer", nodes.answer),
    ]:
        graph.add_node(name, method)
    graph.add_edge(START, "UnderstandQuestion")
    graph.add_conditional_edges(
        "UnderstandQuestion", after_node, {"next": "SelectSchema", "failure": "GenerateAnswer"}
    )
    graph.add_conditional_edges(
        "SelectSchema", after_node, {"next": "GenerateSQL", "failure": "GenerateAnswer"}
    )
    graph.add_conditional_edges(
        "GenerateSQL", after_node, {"next": "ValidateSQL", "failure": "ClassifyFailure"}
    )
    graph.add_conditional_edges(
        "ValidateSQL", after_node, {"next": "ExecuteSQL", "failure": "ClassifyFailure"}
    )
    graph.add_conditional_edges(
        "ExecuteSQL", after_node, {"next": "GenerateAnswer", "failure": "ClassifyFailure"}
    )
    graph.add_conditional_edges(
        "ClassifyFailure", after_classify, {"retry": "GenerateSQL", "answer": "GenerateAnswer"}
    )
    graph.add_edge("GenerateAnswer", END)
    return graph.compile()
