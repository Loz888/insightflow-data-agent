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
