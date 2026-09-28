"""Server-owned time values used by persistence and public projections."""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime, timedelta

_RFC3339 = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)$")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def now_ms() -> int:
    """Return the daemon's UTC wall-clock time as integer milliseconds."""

    return time.time_ns() // 1_000_000


def format_timestamp(value: int | None) -> str | None:
    """Render an internal UTC millisecond value as RFC3339 with millisecond precision."""

    if value is None:
        return None
    instant = _EPOCH + timedelta(milliseconds=value)
    return instant.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_timestamp(value: str | None) -> int | None:
    """Parse an RFC3339 timestamp into UTC milliseconds.

    Public filters must carry an explicit offset (or ``Z``); naive values are
    rejected so a local machine timezone cannot silently change an audit query.
    """

    if value is None:
        return None
    text = value.strip()
    if not text:
        raise ValueError("timestamp_empty")
    if not _RFC3339.fullmatch(text):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?", text):
            raise ValueError("timestamp_timezone_required")
        raise ValueError("timestamp_rfc3339_required")
    normalized = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp_timezone_required")
    try:
        delta = parsed.astimezone(UTC) - _EPOCH
    except OverflowError as exc:
        raise ValueError("timestamp_out_of_range") from exc
    return (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
