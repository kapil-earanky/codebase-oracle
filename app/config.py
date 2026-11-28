from functools import lru_cache

from pydantic import BaseModel, Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class _EnvBaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

class PostgresSettings(_EnvBaseSettings):
    """Postgres configurations matching the env prefixes directly."""
    host: str = "localhost"
    port: int = 5432
    user: str
    password: str
    db: str

    # Property helper to securely build the standard connection URI
    @property
    def dsn(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.user,
                password=self.password,
                host=self.host,
                port=self.port,
                path=self.db))

    model_config = SettingsConfigDict(env_prefix="POSTGRES_")


class RedisSettings(_EnvBaseSettings):
    """Redis configurations matching the env prefixes directly."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None

    @property
    def dsn(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"

    model_config = SettingsConfigDict(env_prefix="REDIS_")


class OtelSettings(_EnvBaseSettings):
    """OpenTelemetry environment naming standards matching OTEL specifications."""
    service_name: str = "app-service"
    exporter_otlp_endpoint: str = "http://localhost:4317"
    traces_sampler: str = "always_on"
    model_config = SettingsConfigDict(env_prefix="OTEL_")

class EmbeddingModelSettings(_EnvBaseSettings):
    """Embedding model settings."""
    model: str = "BAAI/bge-base-en-v1.5"
    dim: int = 768    
    max_tokens: int = 512
    model_config = SettingsConfigDict(env_prefix="EMBEDDING_")

class AppSettings(BaseModel):
    """Main Settings Class composed of individual service domains."""
    
    # Instantiate child sub-models via Default Factories to parse the environment
    postgres: PostgresSettings = Field(default_factory=PostgresSettings) # type: ignore[arg-type]
    redis: RedisSettings = Field(default_factory=RedisSettings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    embedding: EmbeddingModelSettings = Field(default_factory=EmbeddingModelSettings)

# Globally instantiated config object to import across your app
@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
