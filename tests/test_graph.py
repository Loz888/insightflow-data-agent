from insightflow.agent.graph import build_basic_graph


def test_actual_stategraph():
    graph = build_basic_graph()
    result = graph.invoke({"question": "测试", "session_id": "day1"})
    assert result["trace"] == ["UnderstandQuestion", "GenerateAnswer"]
    assert set(graph.get_graph().nodes) >= {"understand", "finish"}
