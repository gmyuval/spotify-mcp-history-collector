"""API token model for user-facing Bearer tokens (Claude Desktop/Code)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.base import Base, utc_now


class ApiToken(Base):
    """Long-lived API tokens for MCP clients (Claude Desktop, Claude Code).

    Tokens are stored as SHA-256 hashes; the plaintext is shown once on creation.
    Soft-deleted via ``revoked_at`` timestamp.
    """

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_api_tokens_user_revoked", "user_id", "revoked_at"),
        Index("ix_api_tokens_token_hash", "token_hash", unique=True),
    )
