"""Constants for ZIP import processing."""

import re

# Filename patterns for format detection
EXTENDED_HISTORY_PATTERN = re.compile(
    r"(endsong_\d+\.json|Streaming_History_Audio_.*\.json)$",
    re.IGNORECASE,
)
ACCOUNT_DATA_PATTERN = re.compile(r"StreamingHistory\d*\.json$", re.IGNORECASE)

# Fields to strip from raw records (privacy/security)
SENSITIVE_FIELDS_EXTENDED = frozenset(
    {
        "ip_addr_decrypted",
        "ip_addr",
        "user_agent_decrypted",
        "user_agent",
        "username",
        "conn_country",
        "platform",
    }
)

# Default batch size for import processing
DEFAULT_IMPORT_BATCH_SIZE = 5000
