from functools import lru_cache
from urllib.parse import quote

from pydantic import BaseModel, Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class _EnvBaseSettings(BaseSettings):
    """Shared `.env` loading behavior inherited by all domain settings classes."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


class PostgresSettings(_EnvBaseSettings):
    """PostgreSQL connection settings (`POSTGRES_*`)."""

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    user: str
    password: str
    db: str

    @property
    def dsn(self) -> str:
        """Build a safely percent-encoded PostgreSQL connection URI."""
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=quote(self.user, safe=""),
                password=quote(self.password, safe=""),
                host=self.host,
                port=self.port,
                path=self.db,
            )
        )


class RedisSettings(_EnvBaseSettings):
    """Redis connection settings (`REDIS_*`)."""

    model_config = SettingsConfigDict(env_prefix="REDIS_")

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None

    @field_validator("password", mode="before")
    @classmethod
    def _empty_password_to_none(cls, value: object) -> object:
        if isinstance(value, str) and value == "":
            return None
        return value

    @property
    def dsn(self) -> str:
        """Build a safely percent-encoded Redis connection URI."""
        auth = f":{quote(self.password, safe='')}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


class OtelSettings(_EnvBaseSettings):
    """OpenTelemetry exporter settings (`OTEL_*`)."""

    model_config = SettingsConfigDict(env_prefix="OTEL_")

    service_name: str = "codebase-oracle"
    exporter_otlp_endpoint: str = "http://localhost:4317"
    traces_sampler: str = "always_on"


class EmbeddingModelSettings(_EnvBaseSettings):
    """Local embedding model configuration (`EMBEDDING_*`, see ADR-0001)."""

    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")

    model: str = "BAAI/bge-base-en-v1.5"
    dim: int = 768
    max_tokens: int = 512


class AppSettings(BaseModel):
    """Root application settings composed from domain-specific sub-settings."""

    postgres: PostgresSettings = Field(default_factory=PostgresSettings)  # type: ignore[arg-type]
    redis: RedisSettings = Field(default_factory=RedisSettings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    embedding: EmbeddingModelSettings = Field(default_factory=EmbeddingModelSettings)


@lru_cache
def get_settings() -> AppSettings:
    """Return cached application settings (call `.cache_clear()` in tests)."""
    return AppSettings()
