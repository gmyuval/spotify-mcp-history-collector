"""Application-wide dependencies."""

from shared.db import DatabaseManager

db_manager = DatabaseManager.from_env()
