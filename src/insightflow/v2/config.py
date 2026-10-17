from decimal import Decimal
from datetime import datetime, timezone
from typing import Literal
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class V2Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INSIGHTFLOW_V2_", env_file=None, extra="ignore")
    mode: Literal["mock", "deepseek"] = "mock"
    runtime_url: SecretStr
    reader_url: SecretStr
    # Map opaque local bearer secrets to trusted principal IDs. Never supplied by request bodies.
    auth_tokens: dict[str, str]
    model: Literal["deepseek-flash", "deepseek-v4-pro"] = "deepseek-flash"
    thinking_effort: Literal["max"] = "max"
    live_enabled: bool = False
    api_key: SecretStr = SecretStr("")
    reference_time: datetime = datetime(2026, 10, 1, tzinfo=timezone.utc)
    project_budget_usd: Decimal = Field(Decimal("2.00"), gt=0, le=2)
    experiment_id: str = Field("upgrade-v2-20261017", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    input_price_per_million: Decimal = Field(Decimal("0.30"), gt=0)
    output_price_per_million: Decimal = Field(Decimal("1.20"), gt=0)
    request_seconds: float = Field(180, gt=0, le=180)
    queue_seconds: float = Field(3, gt=0, le=30)
    model_timeout: float = Field(30, gt=0, le=30)
    model_concurrency: int = Field(2, ge=1, le=4)
    db_concurrency: int = Field(4, ge=1, le=8)
    active_limit: int = Field(8, ge=1, le=32)
    max_model_calls: int = Field(12, ge=2, le=20)
    max_tool_calls: int = Field(10, ge=1, le=16)
    max_graph_steps: int = Field(26, ge=8, le=50)
    max_sql_repairs: int = Field(2, ge=0, le=2)
    max_output_tokens: int = Field(8192, ge=256, le=16384)
    max_input_bytes: int = Field(24000, ge=2000, le=48000)
    request_token_budget: int = Field(160000, ge=5000, le=160000)
    max_http_attempts: int = Field(500, ge=1, le=1000)
    lease_seconds: float = Field(15, ge=3, le=120)
    idempotency_ttl_seconds: int = Field(86400, ge=60, le=604800)
    retrieval_mode: Literal["full", "rules", "lexical"] = "lexical"
    context_enabled: bool = True
    feedback_enabled: bool = True
    stream_model: bool = False

    @model_validator(mode="after")
    def valid(self):
        if self.reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        if not self.auth_tokens or any(len(k) < 24 or not v for k, v in self.auth_tokens.items()):
            raise ValueError("at least one 24+ character bearer secret and principal required")
        rates = (self.input_price_per_million, self.output_price_per_million, self.project_budget_usd)
        if not all(n.is_finite() for n in rates):
            raise ValueError("finite budget and prices required")
        minimum = {
            "deepseek-flash": (Decimal("0.30"), Decimal("1.20")),
            "deepseek-v4-pro": (Decimal("1.32"), Decimal("3.96")),
        }[self.model]
        if rates[0] < minimum[0] or rates[1] < minimum[1]:
            raise ValueError("rates below verified peak/cache-miss prices")
        if self.mode == "deepseek" and (not self.live_enabled or not self.api_key.get_secret_value()):
            raise ValueError("Live mode requires local key and explicit live_enabled")
        return self
