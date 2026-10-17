import httpx
import pytest
from openai import OpenAI
from insightflow.llm.deepseek import DeepSeekLLMProvider
from insightflow.database.errors import AgentError


@pytest.fixture
def live_config(monkeypatch):
    monkeypatch.setenv("INSIGHTFLOW_ENABLE_LIVE", "true")
    monkeypatch.setenv("INSIGHTFLOW_INPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("INSIGHTFLOW_OUTPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("INSIGHTFLOW_MAX_MODEL_CALLS", "2")


def client(handler):
    return OpenAI(
        api_key="test-key",
        base_url="https://mock.invalid",
        max_retries=0,
        timeout=1,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_live_disabled(monkeypatch):
    monkeypatch.delenv("INSIGHTFLOW_ENABLE_LIVE", raising=False)
    with pytest.raises(AgentError):
        DeepSeekLLMProvider()


@pytest.mark.parametrize("code,retry", [(429, True), (500, True), (401, False)])
def test_status_sanitization(live_config, code, retry):
    provider = DeepSeekLLMProvider(
        client(
            lambda req: httpx.Response(code, json={"error": {"message": "credential must never propagate"}})
        )
    )
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.retryable == retry
    assert "credential" not in str(exc.value)


def test_invalid_json_timeout_and_budget(live_config):
    def handler(req):
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "mock",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "NOT JSON"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    provider = DeepSeekLLMProvider(client(handler))
    for _ in range(2):
        with pytest.raises(AgentError):
            provider.understand("订单", {})
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.kind.value == "BUDGET_EXHAUSTED"

    def timeout(req):
        raise httpx.ReadTimeout("secret data")

    with pytest.raises(AgentError) as exc:
        DeepSeekLLMProvider(client(timeout)).understand("订单", {})
    assert "secret" not in str(exc.value)
