"""Spotify API client exceptions."""


class SpotifyClientError(Exception):
    """Base exception for Spotify client errors."""


class SpotifyAuthError(SpotifyClientError):
    """Spotify returned 401 Unauthorized and token refresh did not resolve it."""


class SpotifyRateLimitError(SpotifyClientError):
    """Spotify returned 429 Too Many Requests and retries were exhausted."""

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        msg = "Spotify rate limit exceeded"
        if retry_after is not None:
            msg += f" (retry-after: {retry_after}s)"
        super().__init__(msg)


class SpotifyServerError(SpotifyClientError):
    """Spotify returned a 5xx server error and retries were exhausted."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Spotify server error: HTTP {status_code}" + (f" — {detail}" if detail else ""))


class SpotifyRequestError(SpotifyClientError):
    """Spotify returned a non-retryable client error (4xx other than 401/429)."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Spotify request error: HTTP {status_code}" + (f" — {detail}" if detail else ""))
