"""JSON log formatter for structured logging output."""

import json
import logging
from datetime import UTC, datetime


class JSONLogFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects.

    Output format::

        {"timestamp": "...", "level": "INFO", "service": "api",
         "logger": "app.main", "message": "...", "request_id": "...", ...}
    """

    def __init__(self, service: str = "api") -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include request_id if available (set by RequestIDMiddleware)
        request_id = getattr(record, "request_id", None)
        if request_id:
            entry["request_id"] = request_id

        # Include exception info if present
        if record.exc_info and record.exc_info[1] is not None:
            entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(entry, default=str)
