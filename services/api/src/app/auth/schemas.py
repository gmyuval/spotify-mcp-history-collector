"""Pydantic schemas for Spotify API responses and auth endpoint responses."""

from pydantic import BaseModel


class SpotifyTokenResponse(BaseModel):
    """Response from Spotify's /api/token endpoint."""

    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str | None = None
    scope: str | None = None


class SpotifyProfile(BaseModel):
    """User profile from Spotify's /v1/me endpoint."""

    id: str
    display_name: str | None = None
    email: str | None = None
    country: str | None = None
    product: str | None = None


class SpotifyProfileSummary(BaseModel):
    """Minimal user profile returned in API responses."""

    spotify_user_id: str
    display_name: str | None = None


class AuthCallbackResponse(BaseModel):
    """Response returned from the OAuth callback endpoint."""

    message: str
    user: SpotifyProfileSummary
    is_new_user: bool
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


class JWTTokenResponse(BaseModel):
    """Response for the token refresh endpoint."""

    access_token: str
    expires_in: int
    token_type: str = "Bearer"


class RefreshTokenRequest(BaseModel):
    """Request body for POST /auth/refresh (API clients)."""

    refresh_token: str
