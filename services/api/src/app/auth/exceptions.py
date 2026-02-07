"""Domain exceptions for the auth module."""


class OAuthError(Exception):
    """Base exception for OAuth errors."""


class InvalidStateError(OAuthError):
    """OAuth state parameter validation failed (CSRF protection)."""


class SpotifyAPIError(OAuthError):
    """Spotify API returned an error response."""

    def __init__(self, action: str, status_code: int, detail: str) -> None:
        self.action = action
        self.spotify_status_code = status_code
        self.detail = detail
        super().__init__(f"Spotify API error during {action}: HTTP {status_code} — {detail}")


class TokenNotFoundError(Exception):
    """No token record found for the requested user."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        super().__init__(f"No token found for user_id={user_id}")


class TokenRefreshError(Exception):
    """Failed to refresh a Spotify access token."""

    def __init__(self, user_id: int, detail: str) -> None:
        self.user_id = user_id
        self.detail = detail
        super().__init__(f"Token refresh failed for user {user_id}: {detail}")
