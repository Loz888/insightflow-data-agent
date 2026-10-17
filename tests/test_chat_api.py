from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from insightflow.api.app import create_app
from insightflow.api.schemas import Evidence, ChatResponse
from insightflow.config import Settings


@pytest.mark.integration
def test_chat_and_live_schema(database_urls):
    with TestClient(create_app(Settings(database_url=SecretStr(database_urls[0])))) as client:
        schema = client.get("/schema").json()
        assert len(schema["tables"]) == 5 and "password" not in str(schema).lower()
        response = client.post(
            "/chat", json={"session_id": "api-demo", "question": "2026年9月退款率是多少？"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None and body["evidence"]["row_count"] == 1
        follow = client.post("/chat", json={"session_id": "api-demo", "question": "那华东地区呢？"}).json()
        assert "华东" in follow["sql"] and "2026-09" in follow["sql"]
        assert follow["limitations"] and follow["request_id"]
        failed = client.post(
            "/chat", json={"session_id": "unknown", "question": "员工流失率为何上升？"}
        ).json()
        assert failed["error"]["kind"] == "CLARIFICATION_REQUIRED" and failed["evidence"] == {}


@pytest.mark.parametrize(
    "body",
    [
        {"session_id": "../../secret", "question": "订单总数"},
        {"session_id": "valid", "question": ""},
        {"session_id": "valid", "question": " " * 5},
        {"session_id": "x" * 65, "question": "订单总数"},
        {"session_id": "valid", "question": "x" * 1001},
        {"session_id": "valid", "question": "订单总数", "sql": "DROP TABLE x"},
    ],
)
def test_request_validation(body):
    with TestClient(create_app(Settings(database_url=SecretStr("")))) as client:
        assert client.post("/chat", json=body).status_code == 422


def test_evidence_output_shape():
    with pytest.raises(ValidationError):
        Evidence(columns=["x"], rows=[[1, 2]], row_count=1)
    with pytest.raises(ValidationError):
        ChatResponse(
            answer="x",
            sql="",
            tables_used=[],
            evidence={"malformed": True},
            limitations=[],
            error=None,
            request_id="x",
            retries=0,
            model_type="mock",
        )


@pytest.mark.integration
def test_concurrent_sessions_do_not_mix(database_urls):
    from insightflow.agent.service import AgentService

    svc = AgentService(Settings(database_url=SecretStr(database_urls[0])))
    try:

        def conversation(region):
            key = "thread-" + region
            svc.run("2026年9月已支付销售收入是多少？", key)
            return svc.run("那" + region + "地区呢？", key)

        with ThreadPoolExecutor(max_workers=2) as executor:
            east, south = list(executor.map(conversation, ["华东", "华南"]))
        assert east["plan"]["region"] == "华东" and south["plan"]["region"] == "华南"
        assert east["plan"]["month"] == south["plan"]["month"] == "2026-09"
    finally:
        svc.close()
