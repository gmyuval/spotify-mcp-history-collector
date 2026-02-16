"""FastAPI dependencies for JWT-authenticated endpoints."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request


async def get_current_user(request: Request) -> int:
    """Require a valid JWT user. Returns user_id.

    Raises HTTPException(401) if no authenticated user.
    """
    user_id: int | None = getattr(request.state, "user_id", None)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


async def get_optional_user(request: Request) -> int | None:
    """Return user_id if authenticated, None otherwise.

    Does NOT raise — use for endpoints with optional auth.
    """
    return getattr(request.state, "user_id", None)


# Type aliases for Annotated dependencies
CurrentUser = Annotated[int, Depends(get_current_user)]
OptionalUser = Annotated[int | None, Depends(get_optional_user)]
