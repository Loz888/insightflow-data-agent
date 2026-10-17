from fastapi.testclient import TestClient
from insightflow.api.app import create_app
from insightflow.config import Settings


def test_health_without_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with TestClient(create_app(Settings())) as client:
        assert client.get("/health").json() == {"status": "ok", "mode": "mock"}
        schema = client.get("/schema")
        assert schema.status_code == 200
        assert schema.json()["schema_name"] == "business"
        assert "password" not in schema.text.lower()
