"""Tests for CollectorSettings."""

from collector.settings import CollectorSettings


def test_defaults() -> None:
    """Settings have sensible defaults."""
    settings = CollectorSettings(
        SPOTIFY_CLIENT_ID="cid",
        SPOTIFY_CLIENT_SECRET="csecret",
        TOKEN_ENCRYPTION_KEY="key",
    )
    assert settings.COLLECTOR_INTERVAL_SECONDS == 600
    assert settings.INITIAL_SYNC_ENABLED is True
    assert settings.INITIAL_SYNC_MAX_DAYS == 30
    assert settings.INITIAL_SYNC_MAX_REQUESTS == 200
    assert settings.INITIAL_SYNC_CONCURRENCY == 2
    assert settings.IMPORT_MAX_ZIP_SIZE_MB == 500
    assert settings.IMPORT_MAX_RECORDS == 5_000_000
    assert settings.TOKEN_EXPIRY_BUFFER_SECONDS == 60


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[name-defined]  # noqa: F821
    """Settings can be overridden via environment variables."""
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "env-id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "env-key")
    monkeypatch.setenv("COLLECTOR_INTERVAL_SECONDS", "120")
    monkeypatch.setenv("INITIAL_SYNC_ENABLED", "false")

    settings = CollectorSettings()
    assert settings.SPOTIFY_CLIENT_ID == "env-id"
    assert settings.COLLECTOR_INTERVAL_SECONDS == 120
    assert settings.INITIAL_SYNC_ENABLED is False
