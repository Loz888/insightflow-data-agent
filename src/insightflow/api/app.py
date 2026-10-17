from fastapi import FastAPI
from insightflow.api.schemas import HealthResponse, SchemaResponse
from insightflow.config import Settings


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    app = FastAPI(title="InsightFlow", version="0.1.0")

    @app.get("/health", response_model=HealthResponse)
    def health():
        return {"status": "ok", "mode": settings.mode}

    @app.get("/schema", response_model=SchemaResponse)
    def schema():
        return {"schema_name": "business", "tables": {}}
    return app


app = create_app()
