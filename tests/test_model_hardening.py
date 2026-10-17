import json
import httpx
import pytest
from openai import OpenAI
from insightflow.llm.deepseek import DeepSeekLLMProvider
from insightflow.database.errors import AgentError


@pytest.fixture
def authorized_http_mock(monkeypatch):
    # Local MockTransport only; this fixture never authorizes an external request.
    monkeypatch.setenv("INSIGHTFLOW_ENABLE_PAID_EVAL", "1")
    monkeypatch.setenv("INSIGHTFLOW_ENABLE_LIVE", "true")
    monkeypatch.setenv("INSIGHTFLOW_INPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("INSIGHTFLOW_OUTPUT_PRICE_PER_MILLION", "1")
    monkeypatch.setenv("INSIGHTFLOW_MAX_MODEL_CALLS", "4")
    monkeypatch.setenv("INSIGHTFLOW_MODEL_RETRIES", "1")


def sdk(handler):
    return OpenAI(
        api_key="test-key",
        base_url="https://mock.invalid",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def response(content, finish="stop", usage=True):
    body = {
        "id": "local",
        "object": "chat.completion",
        "created": 0,
        "model": "mock",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": finish}
        ],
    }
    if usage:
        body["usage"] = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    return httpx.Response(200, json=body)


def test_old_flag_cannot_authorize_paid_request(monkeypatch):
    monkeypatch.setenv("INSIGHTFLOW_ENABLE_LIVE", "true")
    monkeypatch.delenv("INSIGHTFLOW_ENABLE_PAID_EVAL", raising=False)
    called = []
    with pytest.raises(AgentError):
        DeepSeekLLMProvider(sdk(lambda req: called.append(req)))
    assert called == []


@pytest.mark.parametrize(
    "code,kind,attempts",
    [
        (401, "MODEL_AUTH_ERROR", 1),
        (403, "MODEL_AUTH_ERROR", 1),
        (429, "MODEL_RATE_LIMIT", 2),
        (503, "MODEL_UPSTREAM_ERROR", 2),
    ],
)
def test_typed_http_errors_and_bounded_retry(authorized_http_mock, code, kind, attempts):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(code, json={"error": {"message": "never reveal credential"}})

    provider = DeepSeekLLMProvider(sdk(handler))
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.kind.value == kind and len(calls) == attempts
    assert "credential" not in str(exc.value)


@pytest.mark.parametrize(
    "content,finish,kind",
    [
        ("", "stop", "MODEL_INVALID_RESPONSE"),
        ("   ", "stop", "MODEL_INVALID_RESPONSE"),
        ("{bad", "stop", "MODEL_INVALID_RESPONSE"),
        ('{"metric":"order_count","extra":"bad"}', "stop", "MODEL_INVALID_RESPONSE"),
        ('{"metric":"order_count"}', "length", "MODEL_OUTPUT_TRUNCATED"),
    ],
)
def test_structure_empty_and_truncation(authorized_http_mock, content, finish, kind):
    provider = DeepSeekLLMProvider(sdk(lambda req: response(content, finish)))
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.kind.value == kind


def test_success_after_rate_limit_and_usage(authorized_http_mock):
    calls = []

    def handler(req):
        calls.append(req)
        return (
            httpx.Response(429, json={"error": {}})
            if len(calls) == 1
            else response('{"metric":"order_count"}')
        )

    provider = DeepSeekLLMProvider(sdk(handler))
    assert provider.understand("订单", {}).metric == "order_count"
    assert provider.calls == 2
    assert provider.usage()["usage_known"] is False  # retry's billed usage is unknown, never invented
    successful = DeepSeekLLMProvider(sdk(lambda req: response('{"metric":"order_count"}')))
    successful.understand("订单", {})
    assert successful.usage()["input_tokens"] == 10 and successful.usage()["output_tokens"] == 5
    assert successful.usage()["total_tokens"] == 15 and successful.usage()["usage_known"]


def test_timeout_budget_and_unknown_usage(authorized_http_mock, monkeypatch):
    monkeypatch.setenv("INSIGHTFLOW_MAX_MODEL_CALLS", "1")
    called = []

    def handler(req):
        called.append(req)
        raise httpx.ReadTimeout("password must not escape")

    provider = DeepSeekLLMProvider(sdk(handler))
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.kind.value == "MODEL_BUDGET_EXHAUSTED" and len(called) == 1
    assert "password" not in str(exc.value)
    provider = DeepSeekLLMProvider(sdk(lambda req: response('{"metric":"order_count"}', usage=False)))
    provider.understand("订单", {})
    assert provider.usage()["total_tokens"] is None


def test_no_paid_gate_writes_not_run_without_client(monkeypatch, tmp_path):
    from insightflow.evaluation.real_model import main

    monkeypatch.delenv("INSIGHTFLOW_ENABLE_PAID_EVAL", raising=False)
    monkeypatch.setattr("sys.argv", ["real_model", "--output", str(tmp_path)])
    assert main() == 0
    data = json.loads((tmp_path / "summary.json").read_text())
    assert data["status"] == "NOT_RUN" and data["api_calls"] == 0
    assert (tmp_path / "runs.jsonl").read_text() == ""


def test_timeout_is_classified_after_bounded_attempts(authorized_http_mock):
    calls = []

    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout("sensitive upstream detail")

    provider = DeepSeekLLMProvider(sdk(handler))
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.kind.value == "MODEL_TIMEOUT" and len(calls) == 2
    assert "sensitive" not in str(exc.value)


def test_conservative_cost_reservation_stops_before_http(authorized_http_mock, monkeypatch):
    monkeypatch.setenv("INSIGHTFLOW_MAX_COST_USD", "0.000000001")
    calls = []
    provider = DeepSeekLLMProvider(sdk(lambda req: calls.append(req)))
    with pytest.raises(AgentError) as exc:
        provider.understand("订单", {})
    assert exc.value.kind.value == "MODEL_BUDGET_EXHAUSTED"
    assert calls == [] and provider.calls == 0
