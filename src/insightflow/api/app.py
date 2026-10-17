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
        if not settings.database_url.get_secret_value():
            return {"schema_name": "business", "tables": {}}
        from insightflow.database.metadata import read_catalog

        catalog = read_catalog(settings.database_url.get_secret_value())
        return {"schema_name": "business", "tables": {k: list(v.columns) for k, v in catalog.items()}}

    return app


app = create_app()
