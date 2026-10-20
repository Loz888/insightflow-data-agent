import os
import subprocess
import sys
import pytest


@pytest.mark.parametrize("optimized", [False, True])
def test_legacy_budget_config_is_rejected_before_http_even_under_optimization(optimized):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("INSIGHTFLOW_", "DEEPSEEK_"))}
    env.update(
        INSIGHTFLOW_ENABLE_PAID_EVAL="1",
        INSIGHTFLOW_ENABLE_LIVE="true",
        INSIGHTFLOW_INPUT_PRICE_PER_MILLION="0.30",
        INSIGHTFLOW_OUTPUT_PRICE_PER_MILLION="1.20",
    )
    code = """
import os
from insightflow.llm.deepseek import DeepSeekLLMProvider
from insightflow.database.errors import AgentError, ErrorKind
for key,value in [('INSIGHTFLOW_MAX_COST_USD','NaN'),('INSIGHTFLOW_MAX_MODEL_CALLS','0'),('INSIGHTFLOW_INPUT_PRICE_PER_MILLION','-1'),('INSIGHTFLOW_DEEPSEEK_MODEL','unknown-model')]:
    previous=os.environ.get(key)
    os.environ[key]=value
    try:
        DeepSeekLLMProvider(client=object())
    except AgentError as exc:
        if exc.kind!=ErrorKind.MODEL_BUDGET_EXHAUSTED: raise RuntimeError('wrong validation error')
    else:
        raise RuntimeError('invalid configuration accepted')
    finally:
        if previous is None: os.environ.pop(key,None)
        else: os.environ[key]=previous
"""
    command = [sys.executable, *(["-O"] if optimized else []), "-c", code]
    completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, "Budget validation failed in the isolated interpreter"
