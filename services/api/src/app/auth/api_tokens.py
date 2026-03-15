"""API token service — generate, validate, list, and revoke user tokens."""

import hashlib
import secrets
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.base import utc_now
from shared.db.models import ApiToken

# Token format: "smcp_" prefix + 32 bytes URL-safe base64 (~43 chars)
_TOKEN_PREFIX = "smcp_"
_TOKEN_BYTES = 32
_DISPLAY_PREFIX_LEN = 8  # chars of the full token stored for display


class CreatedToken(BaseModel):
    """Result of token creation — plaintext shown once, then discarded."""

    model_config = ConfigDict(frozen=True)

    token_id: int
    name: str
    token: str
    prefix: str
    created_at: datetime


def _hash_token(raw_token: str) -> str:
    """SHA-256 hash a raw token string."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


def generate_raw_token() -> str:
    """Generate a new raw token string with the smcp_ prefix."""
    return _TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_BYTES)


class ApiTokenService:
    """CRUD operations for user API tokens."""

    @staticmethod
    async def create(user_id: int, name: str, session: AsyncSession) -> CreatedToken:
        """Create a new API token. Returns the plaintext token (shown once)."""
        raw_token = generate_raw_token()
        token_hash = _hash_token(raw_token)
        prefix = raw_token[:_DISPLAY_PREFIX_LEN]

        row = ApiToken(
            user_id=user_id,
            name=name,
            token_prefix=prefix,
            token_hash=token_hash,
        )
        session.add(row)
        await session.flush()

        return CreatedToken(
            token_id=row.id,
            name=row.name,
            token=raw_token,
            prefix=prefix,
            created_at=row.created_at,
        )

    @staticmethod
    async def validate(raw_token: str, session: AsyncSession) -> int | None:
        """Validate a raw token and return the user_id, or None if invalid/revoked.

        Also updates ``last_used_at`` on success.

        Note: The caller must commit the session for the ``last_used_at``
        update to persist. The ``JWTAuthMiddleware`` handles this by
        committing after the downstream response completes.
        """
        token_hash = _hash_token(raw_token)
        result = await session.execute(
            select(ApiToken.id, ApiToken.user_id, ApiToken.revoked_at).where(ApiToken.token_hash == token_hash)
        )
        row = result.one_or_none()
        if row is None or row.revoked_at is not None:
            return None

        # Update last_used_at
        await session.execute(update(ApiToken).where(ApiToken.id == row.id).values(last_used_at=utc_now()))

        return int(row.user_id)

    @staticmethod
    async def list_tokens(user_id: int, session: AsyncSession) -> list[ApiToken]:
        """List all non-revoked tokens for a user."""
        result = await session.execute(
            select(ApiToken)
            .where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
            .order_by(ApiToken.created_at.desc())
        )
        return list(result.scalars().all())

    @staticmethod
    async def revoke(token_id: int, user_id: int, session: AsyncSession) -> bool:
        """Revoke a token by setting revoked_at. Returns True if found and revoked."""
        result = await session.execute(
            update(ApiToken)
            .where(ApiToken.id == token_id, ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))
            .values(revoked_at=utc_now())
        )
        return bool(result.rowcount > 0)  # type: ignore[attr-defined]
