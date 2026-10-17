from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INSIGHTFLOW_", env_file=None, extra="ignore")
    database_url: SecretStr = SecretStr("")
    mode: str = "mock"
    statement_timeout_ms: int = Field(1500, ge=1, le=10000)
    lock_timeout_ms: int = Field(200, ge=1, le=1000)
    max_rows: int = Field(100, ge=1, le=1000)
    max_bytes: int = Field(32768, ge=100, le=1048576)
    pool_size: int = Field(2, ge=1, le=4)
    max_sql_retries: int = Field(2, ge=0, le=2)
    max_context_tokens: int = Field(6000, ge=100, le=16000)
    max_history_turns: int = Field(4, ge=0, le=10)
    max_schema_items: int = Field(5, ge=1, le=5)
