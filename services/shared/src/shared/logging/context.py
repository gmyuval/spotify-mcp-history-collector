"""Ambient logging context — thread/task-local user_id and job_run_id via contextvars.

Usage in async code:
    LogContext.set_user_id(user_id)
    LogContext.set_job_run_id(job_run.id)
    logger.info("...")  # DBLogHandler picks up context automatically

Usage with explicit scope:
    async with log_context(user_id=5, job_run_id=12):
        ...
"""

import contextlib
import contextvars
from collections.abc import AsyncGenerator

_user_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar("log_user_id", default=None)
_job_run_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar("log_job_run_id", default=None)
_import_job_id_var: contextvars.ContextVar[int | None] = contextvars.ContextVar("log_import_job_id", default=None)


class LogContext:
    """Static helpers to get/set ambient logging context variables."""

    @staticmethod
    def set_user_id(user_id: int | None) -> contextvars.Token[int | None]:
        return _user_id_var.set(user_id)

    @staticmethod
    def get_user_id() -> int | None:
        return _user_id_var.get()

    @staticmethod
    def set_job_run_id(job_run_id: int | None) -> contextvars.Token[int | None]:
        return _job_run_id_var.set(job_run_id)

    @staticmethod
    def get_job_run_id() -> int | None:
        return _job_run_id_var.get()

    @staticmethod
    def set_import_job_id(import_job_id: int | None) -> contextvars.Token[int | None]:
        return _import_job_id_var.set(import_job_id)

    @staticmethod
    def get_import_job_id() -> int | None:
        return _import_job_id_var.get()

    @staticmethod
    def clear() -> None:
        """Reset all context variables to None."""
        _user_id_var.set(None)
        _job_run_id_var.set(None)
        _import_job_id_var.set(None)


@contextlib.asynccontextmanager
async def log_context(
    user_id: int | None = None,
    job_run_id: int | None = None,
    import_job_id: int | None = None,
) -> AsyncGenerator[None]:
    """Async context manager that sets logging context and restores it on exit."""
    tokens = (
        LogContext.set_user_id(user_id),
        LogContext.set_job_run_id(job_run_id),
        LogContext.set_import_job_id(import_job_id),
    )
    try:
        yield
    finally:
        _user_id_var.reset(tokens[0])
        _job_run_id_var.reset(tokens[1])
        _import_job_id_var.reset(tokens[2])
