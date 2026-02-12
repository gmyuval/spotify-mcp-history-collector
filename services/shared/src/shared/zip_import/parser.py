"""Streaming ZIP parser — extracts and normalizes Spotify export JSON files."""

import logging
import zipfile
from collections.abc import Generator
from pathlib import Path

import ijson  # type: ignore[import-untyped]

from shared.zip_import.constants import (
    ACCOUNT_DATA_PATTERN,
    DEFAULT_IMPORT_BATCH_SIZE,
    EXTENDED_HISTORY_PATTERN,
    SENSITIVE_FIELDS_EXTENDED,
)
from shared.zip_import.models import NormalizedPlayRecord
from shared.zip_import.normalizers import (
    normalize_account_data_record,
    normalize_extended_record,
)

logger = logging.getLogger(__name__)


class ZipFormatError(Exception):
    """Raised when a ZIP file has no recognizable Spotify export files."""


class ZipImportParser:
    """Streaming parser for Spotify data export ZIP files.

    Opens a ZIP, detects the export format, and yields NormalizedPlayRecord
    batches without loading the entire file into memory.
    """

    def __init__(
        self,
        batch_size: int = DEFAULT_IMPORT_BATCH_SIZE,
        max_records: int = 5_000_000,
    ) -> None:
        self._batch_size = batch_size
        self._max_records = max_records

    def detect_format(self, zip_path: Path) -> str:
        """Detect the export format from filenames inside the ZIP.

        Returns 'extended' or 'account_data'.
        Raises ZipFormatError if no recognizable files found.
        """
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()

        has_extended = any(EXTENDED_HISTORY_PATTERN.search(n) for n in names)
        has_account = any(ACCOUNT_DATA_PATTERN.search(n) for n in names)

        if has_extended:
            return "extended"
        if has_account:
            return "account_data"
        raise ZipFormatError(
            "No recognizable Spotify export files in ZIP. "
            "Expected endsong_*.json, Streaming_History_Audio_*.json, or StreamingHistory*.json"
        )

    def iter_batches(
        self,
        zip_path: Path,
        format_name: str,
    ) -> Generator[list[NormalizedPlayRecord]]:
        """Yield batches of normalized records from the ZIP.

        This is a synchronous generator (ZIP/ijson are sync I/O).
        Yields list[NormalizedPlayRecord] batches of self._batch_size.
        """
        if format_name == "extended":
            pattern = EXTENDED_HISTORY_PATTERN
            normalizer = normalize_extended_record
        elif format_name == "account_data":
            pattern = ACCOUNT_DATA_PATTERN
            normalizer = normalize_account_data_record
        else:
            raise ValueError(f"Unknown format_name: {format_name!r}")

        total_parsed = 0
        batch: list[NormalizedPlayRecord] = []

        with zipfile.ZipFile(zip_path, "r") as zf:
            matching_files = sorted(n for n in zf.namelist() if pattern.search(n))

            for filename in matching_files:
                logger.info("Parsing ZIP entry: %s", filename)

                with zf.open(filename) as f:
                    for raw_record in ijson.items(f, "item"):
                        if total_parsed >= self._max_records:
                            logger.warning(
                                "Reached max records cap (%d), stopping",
                                self._max_records,
                            )
                            if batch:
                                yield batch
                            return

                        # Strip sensitive fields from extended format
                        if format_name == "extended":
                            for field in SENSITIVE_FIELDS_EXTENDED:
                                raw_record.pop(field, None)

                        record = normalizer(raw_record)
                        if record is None:
                            continue

                        total_parsed += 1
                        batch.append(record)

                        if len(batch) >= self._batch_size:
                            yield batch
                            batch = []

        if batch:
            yield batch
