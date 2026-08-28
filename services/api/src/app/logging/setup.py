"""Structured logging configuration for the API service."""

import logging
import sys

from app.constants import ServiceName
from app.logging.formatter import JSONLogFormatter


def configure_logging(service: ServiceName = ServiceName.API) -> None:
    """Set up structured JSON logging on the root logger."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # httpx includes full request URLs at INFO, which can expose Spotify
    # resource identifiers and query values through otherwise ordinary logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONLogFormatter(service=service))
    root.addHandler(handler)
