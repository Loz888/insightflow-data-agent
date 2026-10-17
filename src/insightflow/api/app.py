from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from insightflow.api.schemas import HealthResponse, SchemaResponse
from insightflow.api.routes import router
from insightflow.config import Settings


def create_app(settings: Settings | None = None, provider=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        from insightflow.agent.service import AgentService

        app.state.service = (
            AgentService(settings, provider) if settings.database_url.get_secret_value() else None
        )
        try:
            yield
        finally:
            if app.state.service:
                app.state.service.close()

    app = FastAPI(title="InsightFlow", version="0.1.0", lifespan=lifespan)
    app.include_router(router)

    @app.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok", "mode": settings.mode}

    @app.get("/schema", response_model=SchemaResponse)
    def schema():
        service = app.state.service
        return {
            "schema_name": "business",
            "tables": {k: list(v.columns) for k, v in service.catalog.items()} if service else {},
        }

    return app


logging.basicConfig(level=logging.INFO, format="%(message)s")
app = create_app()
