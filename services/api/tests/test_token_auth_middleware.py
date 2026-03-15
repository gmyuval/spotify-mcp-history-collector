"""Tests for API token authentication in JWTAuthMiddleware."""

from starlette.requests import Request

from app.auth.middleware import JWTAuthMiddleware


class TestExtractApiToken:
    """Unit tests for the static _extract_api_token method."""

    def _make_request(self, auth_header: str | None = None) -> Request:
        scope = {"type": "http", "headers": []}
        if auth_header:
            scope["headers"] = [(b"authorization", auth_header.encode())]
        return Request(scope)

    def test_extracts_smcp_token(self) -> None:
        request = self._make_request("Bearer smcp_abc123")
        result = JWTAuthMiddleware._extract_api_token(request)
        assert result == "smcp_abc123"

    def test_ignores_jwt_token(self) -> None:
        request = self._make_request("Bearer eyJ.abc.def")
        result = JWTAuthMiddleware._extract_api_token(request)
        assert result is None

    def test_ignores_plain_admin_token(self) -> None:
        request = self._make_request("Bearer my-admin-token")
        result = JWTAuthMiddleware._extract_api_token(request)
        assert result is None

    def test_ignores_no_auth_header(self) -> None:
        request = self._make_request()
        result = JWTAuthMiddleware._extract_api_token(request)
        assert result is None


class TestExtractToken:
    """Unit tests for the static _extract_token method — JWT extraction."""

    def _make_request(self, auth_header: str | None = None, cookie: str | None = None) -> Request:
        scope: dict = {"type": "http", "headers": []}
        if auth_header:
            scope["headers"] = [(b"authorization", auth_header.encode())]
        if cookie:
            scope["headers"].append((b"cookie", f"access_token={cookie}".encode()))
        return Request(scope)

    def test_extracts_jwt_from_header(self) -> None:
        request = self._make_request("Bearer eyJ.abc.def")
        result = JWTAuthMiddleware._extract_token(request)
        assert result == "eyJ.abc.def"

    def test_ignores_smcp_token(self) -> None:
        request = self._make_request("Bearer smcp_test123")
        result = JWTAuthMiddleware._extract_token(request)
        assert result is None

    def test_ignores_admin_token(self) -> None:
        request = self._make_request("Bearer admin-token-no-dots")
        result = JWTAuthMiddleware._extract_token(request)
        assert result is None

    def test_falls_back_to_cookie(self) -> None:
        request = self._make_request(cookie="my.jwt.token")
        result = JWTAuthMiddleware._extract_token(request)
        assert result == "my.jwt.token"

    def test_header_takes_precedence(self) -> None:
        request = self._make_request("Bearer header.jwt.token", cookie="cookie.jwt.token")
        result = JWTAuthMiddleware._extract_token(request)
        assert result == "header.jwt.token"


class TestShouldSkip:
    """Unit tests for the _should_skip method."""

    def test_skips_health(self) -> None:
        assert JWTAuthMiddleware._should_skip("/healthz") is True

    def test_skips_docs(self) -> None:
        assert JWTAuthMiddleware._should_skip("/docs") is True

    def test_skips_root(self) -> None:
        assert JWTAuthMiddleware._should_skip("/") is True

    def test_does_not_skip_api(self) -> None:
        assert JWTAuthMiddleware._should_skip("/api/me/tokens") is False

    def test_does_not_skip_mcp(self) -> None:
        assert JWTAuthMiddleware._should_skip("/mcp/v1") is False
