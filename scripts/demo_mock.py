import json
import os
from fastapi.testclient import TestClient
from pydantic import SecretStr
from insightflow.api.app import create_app
from insightflow.config import Settings
from insightflow.database.errors import AgentError


def main():
    settings = Settings(database_url=SecretStr(os.environ["INSIGHTFLOW_TEST_DATABASE_URL"]), mode="mock")
    from insightflow.database.connection import checked_connection

    with checked_connection(settings.database_url.get_secret_value(), test_only=True):
        pass
    with TestClient(create_app(settings)) as client:
        for question in [
            "客户总数是多少？",
            "各商品类别销售收入比较",
            "2026年9月退款率是多少？",
            "那华东地区呢？",
            "员工流失率是多少？",
        ]:
            body = client.post("/chat", json={"session_id": "demo", "question": question}).json()
            print(json.dumps({"question": question, **body}, ensure_ascii=False))
            if "员工" in question:
                assert body["error"]["kind"] == "CLARIFICATION_REQUIRED" and body["evidence"] == {}
            else:
                assert body["error"] is None and body["evidence"]
        try:
            client.app.state.service.tools.execute_readonly_sql("DROP TABLE business.orders")
        except AgentError as exc:
            print(json.dumps({"security_demo": exc.as_dict()}, ensure_ascii=False))
            assert exc.kind.value == "SQL_VALIDATION_ERROR"
        else:
            raise AssertionError("Unsafe SQL was accepted")
    print("PASS: Mock demo (real PostgreSQL + LangGraph + API)")


if __name__ == "__main__":
    main()
