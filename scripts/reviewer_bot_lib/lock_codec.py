"""Lock metadata codec helpers for reviewer-bot state and lock documents."""

from __future__ import annotations

import json
from typing import Any

from .config import LOCK_COMMIT_MARKER, LOCK_METADATA_KEYS, LOCK_SCHEMA_VERSION


def normalize_lock_metadata(lock_meta: dict | None) -> dict:
    normalized: dict[str, Any] = dict.fromkeys(LOCK_METADATA_KEYS)
    normalized["schema_version"] = LOCK_SCHEMA_VERSION

    if not isinstance(lock_meta, dict):
        return normalized

    for key in LOCK_METADATA_KEYS:
        if key == "schema_version":
            schema_value = lock_meta.get("schema_version")
            if isinstance(schema_value, int):
                normalized["schema_version"] = schema_value
            continue
        if key in lock_meta:
            normalized[key] = lock_meta.get(key)

    return normalized
def render_lock_commit_message(lock_meta: dict) -> str:
    lock_json = json.dumps(normalize_lock_metadata(lock_meta), sort_keys=False)
    return f"{LOCK_COMMIT_MARKER}\n{lock_json}"


def parse_lock_commit_message(message: str) -> dict:
    if not message.startswith(f"{LOCK_COMMIT_MARKER}\n"):
        raise RuntimeError("invalid reviewer-bot lock commit message")
    lock_json = message.split("\n", 1)[1]
    try:
        parsed = json.loads(lock_json)
    except json.JSONDecodeError:
        raise RuntimeError("invalid reviewer-bot lock commit message")
    if not isinstance(parsed, dict):
        raise RuntimeError("invalid reviewer-bot lock commit message")
    return normalize_lock_metadata(parsed)
