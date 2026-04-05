"""Lock metadata codec helpers for reviewer-bot state and lock documents."""

from __future__ import annotations

import json
import re
from typing import Any

from .config import (
    LOCK_BLOCK_END_MARKER,
    LOCK_BLOCK_START_MARKER,
    LOCK_COMMIT_MARKER,
    LOCK_METADATA_KEYS,
    LOCK_SCHEMA_VERSION,
)


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


def extract_fenced_json(inner_block: str | None) -> str | None:
    if not inner_block:
        return None
    match = re.search(r"```json\n(.*?)\n```", inner_block, re.DOTALL)
    if match:
        return match.group(1)
    return None


def parse_lock_metadata_block(inner_block: str | None) -> dict:
    lock_json = extract_fenced_json(inner_block)
    if lock_json is None:
        return normalize_lock_metadata(None)
    try:
        parsed = json.loads(lock_json)
    except json.JSONDecodeError:
        return normalize_lock_metadata(None)
    if not isinstance(parsed, dict):
        return normalize_lock_metadata(None)
    return normalize_lock_metadata(parsed)


def render_marked_lock_block(lock_meta: dict) -> str:
    lock_json = json.dumps(normalize_lock_metadata(lock_meta), indent=2, sort_keys=False).rstrip("\n")
    return f"{LOCK_BLOCK_START_MARKER}\n```json\n{lock_json}\n```\n{LOCK_BLOCK_END_MARKER}"


def render_lock_commit_message(lock_meta: dict) -> str:
    lock_json = json.dumps(normalize_lock_metadata(lock_meta), sort_keys=False)
    return f"{LOCK_COMMIT_MARKER}\n{lock_json}"


def parse_lock_commit_message(message: str) -> dict:
    if not message.startswith(f"{LOCK_COMMIT_MARKER}\n"):
        return normalize_lock_metadata({"lock_state": "unlocked"})
    lock_json = message.split("\n", 1)[1]
    try:
        parsed = json.loads(lock_json)
    except json.JSONDecodeError:
        return normalize_lock_metadata({"lock_state": "unlocked"})
    return normalize_lock_metadata(parsed if isinstance(parsed, dict) else None)
