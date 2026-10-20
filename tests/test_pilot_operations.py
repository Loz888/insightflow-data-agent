import asyncio
import os
from pathlib import Path
import httpx
import pytest
from insightflow.v2.api import create_app
from insightflow.v2.config import V2Settings

pytestmark = pytest.mark.integration


def test_real_readiness_failure_alert_condition(database_urls):
    token = "synthetic-readiness-fault-token-only"
    settings = V2Settings(
        runtime_url=os.environ["INSIGHTFLOW_V2_TEST_RUNTIME_URL"],
        reader_url=database_urls[0],
        auth_tokens={token: "readiness"},
        mode="mock",
    )

    async def run():
        app = create_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://fixture", trust_env=False
            ) as client:
                assert (await client.get("/ready")).status_code == 200
                # Close only this fixture's actual bounded executor pool, never the database/service.
                app.state.runtime.executor.pool.close()
                assert (await client.get("/ready")).status_code == 503
                text = (await client.get("/metrics", headers={"Authorization": "Bearer " + token})).text
                assert "insightflow_ready 0.0" in text
                rules = (Path(__file__).resolve().parents[1] / "monitoring/alerts.yml").read_text()
                assert "insightflow_ready == 0" in rules
                assert (await client.get("/health")).status_code == 200

    asyncio.run(run())
