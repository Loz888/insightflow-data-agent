from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    mode: str


class SchemaResponse(BaseModel):
    schema_name: str = "business"
    tables: dict[str, list[str]] = Field(default_factory=dict)
