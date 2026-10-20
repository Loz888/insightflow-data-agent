from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, StrictInt, StrictBool, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
SessionID = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
Scalar = Annotated[str, StringConstraints(max_length=4096)] | StrictInt | StrictBool | None


class HealthResponse(BaseModel):
    status: str
    mode: str


class SchemaResponse(BaseModel):
    schema_name: str = "business"
    tables: dict[str, list[str]] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: SessionID
    question: Text


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[str] = Field(max_length=30)
    column_types: list[StrictInt] | None = Field(default=None, max_length=30)
    rows: list[list[Scalar]] = Field(max_length=1000)
    row_count: int = Field(ge=0, le=1000)

    @model_validator(mode="after")
    def shape(self):
        if self.column_types is not None and (
            len(self.column_types) != len(self.columns)
            or any(t <= 0 or t > 4294967295 for t in self.column_types)
        ):
            raise ValueError("Evidence column type contract mismatch")
        if len(self.rows) != self.row_count or any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("Evidence shape mismatch")
        return self


class ErrorResponse(BaseModel):
    kind: str
    message: str


class EmptyEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatResponse(BaseModel):
    answer: str
    sql: str = Field(max_length=8000)
    tables_used: list[str]
    evidence: Evidence | EmptyEvidence
    limitations: list[str]
    error: ErrorResponse | None
    request_id: str
    retries: int
    model_type: str
