import asyncio
import json
import time
from decimal import Decimal
import httpx
import pytest
from insightflow.v2.config import V2Settings
from insightflow.v2.provider import AsyncDeepSeek, RequestBudget
from insightflow.v2.contracts import Action
from insightflow.v2.telemetry import Telemetry
from insightflow.v2.errors import Fault


class Ledger:
    def __init__(self):
        self.reservations = []
        self.settled = []

    def reserve(self, *args):
        self.reservations.append(args)
        return str(len(self.reservations))

    def settle(self, *args):
        self.settled.append(args)


def settings(**kwargs):
    return V2Settings(
        runtime_url="unused",
        reader_url="unused",
        auth_tokens={"synthetic-protocol-token-only": "a"},
        mode="deepseek",
        live_enabled=True,
        api_key="synthetic-key",
        **kwargs,
    )


def raw(content=None, finish="stop", usage=True):
    return {
        "model": "deepseek-flash",
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "content": content
                    or json.dumps({"call_id": "step_1", "name": "schema", "arguments": {"query": "订单"}})
                },
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30} if usage else None,
    }


def run_protocol(handler, **config):
    async def go():
        ledger = Ledger()
        seen = []

        async def wrapped(request):
            body = json.loads(request.content)
            seen.append(body)
            assert body["thinking"] == {"type": "enabled"} and body["reasoning_effort"] == "max"
            assert request.url == httpx.URL("https://api.deepseek.com/chat/completions")
            return handler(request, len(seen))

        client = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
        p = AsyncDeepSeek(settings(**config), ledger, Telemetry(), client)
        budget = RequestBudget("protocol", time.monotonic() + 10)
        try:
            answer = await p.request("action", {"question": "订单数"}, Action, budget)
            return answer, budget, ledger, seen
        finally:
            await p.close()

    return asyncio.run(go())


def test_max_success_and_scoped_request_budgets():
    out, budget, ledger, seen = run_protocol(lambda r, n: httpx.Response(200, json=raw()))
    assert out.name == "schema" and budget.calls == 1 and budget.usage()["input_tokens"] == 10
    assert ledger.reservations[0][-2:] == (Decimal(".30"), Decimal("1.20"))
    # A new RequestBudget, not a permanent provider lifecycle cap.
    assert run_protocol(lambda r, n: httpx.Response(200, json=raw()))[1].calls == 1


@pytest.mark.parametrize(
    "status,code,calls",
    [
        (401, "MODEL_AUTH", 1),
        (403, "MODEL_AUTH", 1),
        (429, "MODEL_RATE_LIMIT", 2),
        (500, "MODEL_UPSTREAM", 2),
        (503, "MODEL_UPSTREAM", 2),
        (400, "MODEL_INVALID", 1),
    ],
)
def test_http_classification(status, code, calls):
    seen = []

    def handler(r, n):
        seen.append(n)
        return httpx.Response(status, json={"error": "sensitive detail must not escape"})

    with pytest.raises(Fault) as exc:
        run_protocol(handler)
    assert exc.value.code == code and len(seen) == calls
    assert "sensitive" not in str(exc.value)


@pytest.mark.parametrize(
    "content,finish,code",
    [
        ("not JSON", "stop", "MODEL_INVALID"),
        (" ", "stop", "MODEL_INVALID"),
        ("{", "length", "MODEL_TRUNCATED"),
        ('{"call_id":"x","name":"shell","arguments":{}}', "stop", "MODEL_INVALID"),
        ('{"call_id":"x","name":"schema","arguments":{},"unexpected":1}', "stop", "MODEL_INVALID"),
    ],
)
def test_invalid_output(content, finish, code):
    with pytest.raises(Fault) as exc:
        run_protocol(lambda r, n: httpx.Response(200, json=raw(content, finish)))
    assert exc.value.code == code


def test_usage_missing_not_zero():
    _, b, ledger, _ = run_protocol(lambda r, n: httpx.Response(200, json=raw(usage=False)))
    assert b.usage()["input_tokens"] is None and b.unknown_attempts == 1 and ledger.settled[0][2] is None


def test_transport_retry_and_total_deadline():
    def handler(r, n):
        if n == 1:
            raise httpx.ConnectError("private network detail", request=r)
        return httpx.Response(200, json=raw())

    _, b, ledger, _ = run_protocol(handler)
    assert b.calls == 2 and b.retries == 1 and b.usage()["input_tokens"] is None
    with pytest.raises(Fault, match="截止"):
        RequestBudget("x", time.monotonic() - 1).remaining()


def test_stream_complete_and_interrupted():
    def handler(r, n):
        obj = raw()
        content = obj["choices"][0]["message"]["content"]
        chunks = [
            {"model": "deepseek-flash", "choices": [{"delta": {"content": content}, "finish_reason": None}]},
            {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": obj["usage"]},
        ]
        data = "".join("data: " + json.dumps(x) + "\n\n" for x in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=data, headers={"content-type": "text/event-stream"})

    assert run_protocol(handler, stream_model=True)[1].usage()["usage_known"]
    with pytest.raises(Fault) as exc:
        run_protocol(lambda r, n: httpx.Response(200, text='data: {"choices":[]}\n\n'), stream_model=True)
    assert exc.value.code == "MODEL_STREAM_INTERRUPTED"


@pytest.mark.parametrize(
    "kw",
    [
        {"project_budget_usd": "NaN"},
        {"input_price_per_million": "0.01"},
        {"model": "made-up-model"},
        {"live_enabled": False},
        {"auth_tokens": {}},
    ],
)
def test_configuration_not_asserts(kw):
    args = {
        "runtime_url": "unused",
        "reader_url": "unused",
        "auth_tokens": {"synthetic-long-test-token-only": "a"},
        "mode": "deepseek",
        "live_enabled": True,
        "api_key": "synthetic",
    }
    args.update(kw)
    with pytest.raises(ValueError):
        V2Settings(**args)
