"""Shared full-text search utilities for SQLAlchemy queries.

Provides a dialect-aware ``text_match`` function that uses PostgreSQL
full-text search (``to_tsvector``/``plainto_tsquery``) in production and
falls back to case-insensitive LIKE on SQLite (tests).
"""

from typing import Any

from sqlalchemy import func


def text_match(column: Any, query: str, dialect: str) -> Any:
    """Build a text-match clause — PostgreSQL FTS or SQLite ILIKE fallback.

    On PostgreSQL, uses ``to_tsvector``/``plainto_tsquery`` with the
    ``english`` configuration for stemming and word-boundary matching.
    On SQLite (tests), falls back to case-insensitive LIKE.

    Parameters
    ----------
    column:
        A SQLAlchemy column expression (can be cast to String for JSONB).
    query:
        The search text to match against.
    dialect:
        The database dialect name (``"postgresql"`` or ``"sqlite"``).
    """
    if dialect == "postgresql":
        return func.to_tsvector("english", column).op("@@")(func.plainto_tsquery("english", query))
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return column.ilike(f"%{escaped}%", escape="\\")
