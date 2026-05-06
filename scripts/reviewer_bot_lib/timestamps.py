"""Reviewer-bot timestamp normalization helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def parse_iso8601_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str) and value.strip():
        try:
            timestamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def normalize_iso8601_utc_string(value: Any) -> str | None:
    timestamp = parse_iso8601_utc(value)
    return timestamp.isoformat() if timestamp is not None else None
