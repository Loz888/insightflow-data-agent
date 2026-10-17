def after_node(state):
    return "failure" if state.get("error") else "next"


def after_classify(state):
    return "answer" if state.get("error") else "retry"
