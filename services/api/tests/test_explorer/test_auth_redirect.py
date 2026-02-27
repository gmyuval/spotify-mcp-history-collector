"""Tests for OAuth auth redirect (next param) support."""

from cryptography.fernet import Fernet

from app.auth.router import AuthRouter
from app.auth.service import OAuthService
from app.settings import AppSettings

TEST_FERNET_KEY = Fernet.generate_key().decode()


def _test_settings() -> AppSettings:
    return AppSettings(
        SPOTIFY_CLIENT_ID="test-id",
        SPOTIFY_CLIENT_SECRET="test-secret",
        TOKEN_ENCRYPTION_KEY=TEST_FERNET_KEY,
        AUTH_ALLOWED_REDIRECT_ORIGINS="http://localhost:8001,http://localhost:8002,https://music.praxiscode.dev",
    )


class TestValidateNextUrl:
    """Test the _validate_next_url static method."""

    def test_valid_origin_accepted(self) -> None:
        settings = _test_settings()
        result = AuthRouter._validate_next_url("http://localhost:8002/", settings)
        assert result == "http://localhost:8002/"

    def test_valid_origin_with_path(self) -> None:
        settings = _test_settings()
        result = AuthRouter._validate_next_url("https://music.praxiscode.dev/dashboard", settings)
        assert result == "https://music.praxiscode.dev/dashboard"

    def test_invalid_origin_rejected(self) -> None:
        settings = _test_settings()
        result = AuthRouter._validate_next_url("https://evil.com/steal", settings)
        assert result is None

    def test_none_returns_none(self) -> None:
        settings = _test_settings()
        result = AuthRouter._validate_next_url(None, settings)
        assert result is None

    def test_empty_returns_none(self) -> None:
        settings = _test_settings()
        result = AuthRouter._validate_next_url("", settings)
        assert result is None


class TestStatePayloadRoundtrip:
    """Test that next_url survives the OAuth state encode/decode cycle."""

    def test_next_url_in_state(self) -> None:
        settings = _test_settings()
        service = OAuthService(settings)

        # Get auth URL with next param
        url = service.get_authorization_url(next_url="http://localhost:8002/")
        assert "state=" in url

        # Extract state from URL
        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]

        # Parse state payload
        user_id, next_url = service._parse_state_payload(state)
        assert user_id is None
        assert next_url == "http://localhost:8002/"

    def test_user_id_and_next_url_in_state(self) -> None:
        settings = _test_settings()
        service = OAuthService(settings)

        url = service.get_authorization_url(user_id=42, next_url="http://localhost:8002/")

        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]

        user_id, next_url = service._parse_state_payload(state)
        assert user_id == 42
        assert next_url == "http://localhost:8002/"

    def test_user_id_only_backward_compat(self) -> None:
        settings = _test_settings()
        service = OAuthService(settings)

        url = service.get_authorization_url(user_id=42)

        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]

        user_id, next_url = service._parse_state_payload(state)
        assert user_id == 42
        assert next_url is None

    def test_no_payload(self) -> None:
        settings = _test_settings()
        service = OAuthService(settings)

        url = service.get_authorization_url()

        import urllib.parse

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        state = params["state"][0]

        user_id, next_url = service._parse_state_payload(state)
        assert user_id is None
        assert next_url is None

    def test_invalid_state_returns_none(self) -> None:
        settings = _test_settings()
        service = OAuthService(settings)

        # Completely invalid state
        user_id, next_url = service._parse_state_payload("garbage")
        assert user_id is None
        assert next_url is None
