from collections.abc import Iterator

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Ensure every test starts and ends with a clean settings cache and required DB vars."""
    monkeypatch.setenv("POSTGRES_USER", "postgres")
    monkeypatch.setenv("POSTGRES_PASSWORD", "password")
    monkeypatch.setenv("POSTGRES_DB", "codebase_oracle")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_embedding_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBEDDING_MODEL", "custom/model")
    monkeypatch.setenv("EMBEDDING_DIM", "1024")
    monkeypatch.setenv("EMBEDDING_MAX_TOKENS", "256")

    settings = get_settings()

    assert settings.embedding.model == "custom/model"
    assert settings.embedding.dim == 1024
    assert settings.embedding.max_tokens == 256


def test_postgres_settings_and_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "db.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_USER", "oracle")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret123")
    monkeypatch.setenv("POSTGRES_DB", "test_oracle")

    settings = get_settings()

    assert settings.postgres.host == "db.internal"
    assert settings.postgres.port == 5433
    assert settings.postgres.dsn == "postgresql://oracle:secret123@db.internal:5433/test_oracle"


def test_redis_settings_dsn_without_and_with_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("REDIS_PASSWORD", raising=False)
    monkeypatch.setenv("REDIS_HOST", "redis.local")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "2")

    assert get_settings().redis.dsn == "redis://redis.local:6380/2"

    get_settings.cache_clear()
    monkeypatch.setenv("REDIS_PASSWORD", "secret")

    assert get_settings().redis.dsn == "redis://:secret@redis.local:6380/2"


def test_otel_settings_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "oracle-test")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4317")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_always_on")

    settings = get_settings()

    assert settings.otel.service_name == "oracle-test"
    assert settings.otel.exporter_otlp_endpoint == "http://collector:4317"
    assert settings.otel.traces_sampler == "parentbased_always_on"


def test_get_settings_is_cached() -> None:
    first = get_settings()
    second = get_settings()

    assert first is second
