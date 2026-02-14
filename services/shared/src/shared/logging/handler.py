"""Async DB log handler that writes structured log records to the logs table."""

import asyncio
import logging
import sys
import threading
from datetime import UTC, datetime

from shared.db.enums import LogLevel
from shared.db.models.log import Log
from shared.db.session import DatabaseManager

_LEVEL_MAP: dict[int, LogLevel] = {
    logging.DEBUG: LogLevel.DEBUG,
    logging.INFO: LogLevel.INFO,
    logging.WARNING: LogLevel.WARNING,
    logging.ERROR: LogLevel.ERROR,
    logging.CRITICAL: LogLevel.ERROR,
}


class DBLogHandler(logging.Handler):
    """Logging handler that buffers records and flushes them to the database.

    Thread-safe: ``emit()`` appends to a list protected by a lock.
    The buffer is flushed when it reaches ``buffer_size`` or periodically
    every ``flush_interval`` seconds via an asyncio background task.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        service: str = "api",
        buffer_size: int = 50,
        flush_interval: float = 5.0,
    ) -> None:
        super().__init__()
        self._db_manager = db_manager
        self._service = service
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._buffer: list[dict[str, object]] = []
        self._lock = threading.Lock()
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._stopped = False

    def emit(self, record: logging.LogRecord) -> None:
        if self._stopped:
            return

        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC),
            "service": self._service,
            "level": _LEVEL_MAP.get(record.levelno, LogLevel.INFO),
            "message": self.format(record),
            "user_id": getattr(record, "user_id", None),
            "job_run_id": getattr(record, "job_run_id", None),
            "import_job_id": getattr(record, "import_job_id", None),
            "log_metadata": getattr(record, "log_metadata", None),
        }

        with self._lock:
            self._buffer.append(entry)
            should_flush = len(self._buffer) >= self._buffer_size

        if should_flush:
            self._schedule_flush()

    def _schedule_flush(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.flush_buffer()))
        except RuntimeError:
            pass

    async def flush_buffer(self) -> None:
        with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()

        try:
            async with self._db_manager.session() as session:
                for entry in batch:
                    session.add(Log(**entry))
                await session.commit()
        except Exception:
            print(f"DBLogHandler: failed to flush {len(batch)} log entries", file=sys.stderr)

    async def start(self) -> None:
        self._stopped = False
        self._task = asyncio.create_task(self._periodic_flush())

    async def stop(self) -> None:
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.flush_buffer()

    async def _periodic_flush(self) -> None:
        while not self._stopped:
            await asyncio.sleep(self._flush_interval)
            await self.flush_buffer()
