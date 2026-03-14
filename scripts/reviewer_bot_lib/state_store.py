"""State issue parsing, loading, and saving helpers."""

import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any

import yaml

from .config import (
    LOCK_API_RETRY_LIMIT,
    LOCK_BLOCK_END_MARKER,
    LOCK_BLOCK_START_MARKER,
    LOCK_METADATA_KEYS,
    LOCK_RETRY_BASE_SECONDS,
    LOCK_SCHEMA_VERSION,
    STATE_BLOCK_END_MARKER,
    STATE_BLOCK_START_MARKER,
    STATE_ISSUE_NUMBER,
    STATE_READ_RETRY_BASE_SECONDS,
    STATE_READ_RETRY_LIMIT,
    StateIssueBodyParts,
    StateIssueSnapshot,
)


def get_state_issue(bot) -> dict | None:
    """Fetch the state issue from GitHub with retry for transient failures."""
    state_issue_number = getattr(bot, "STATE_ISSUE_NUMBER", STATE_ISSUE_NUMBER)
    state_read_retry_limit = getattr(bot, "STATE_READ_RETRY_LIMIT", STATE_READ_RETRY_LIMIT)
    state_read_retry_base_seconds = getattr(
        bot, "STATE_READ_RETRY_BASE_SECONDS", STATE_READ_RETRY_BASE_SECONDS
    )

    if not state_issue_number:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return None

    for attempt in range(1, state_read_retry_limit + 1):
        response = bot.github_api_request(
            "GET",
            f"issues/{state_issue_number}",
            suppress_error_log=True,
        )

        if response.status_code == 200:
            if not isinstance(response.payload, dict):
                print("ERROR: State issue response payload was not an object", file=sys.stderr)
                return None
            return response.payload

        if response.status_code in {401, 403, 404}:
            print(
                "ERROR: Failed to fetch state issue "
                f"#{state_issue_number} (status {response.status_code}): {response.text}",
                file=sys.stderr,
            )
            return None

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < state_read_retry_limit:
                delay = state_read_retry_base_seconds + random.uniform(0, state_read_retry_base_seconds)
                print(
                    "WARNING: Retryable state issue read failure "
                    f"(status {response.status_code}); retrying ({attempt}/{state_read_retry_limit})",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            print(
                "ERROR: Exhausted retries while fetching state issue "
                f"#{state_issue_number}; last status {response.status_code}: {response.text}",
                file=sys.stderr,
            )
            return None

        print(
            "ERROR: Unexpected status while fetching state issue "
            f"#{state_issue_number}: {response.status_code} {response.text}",
            file=sys.stderr,
        )
        return None

    print(f"ERROR: Failed to fetch state issue #{state_issue_number} after retries", file=sys.stderr)
    return None


def default_state_issue_prefix() -> str:
    return (
        "## Reviewer Bot State\n\n"
        "> WARNING: DO NOT EDIT MANUALLY - This issue is automatically maintained by the reviewer bot.\n"
        "> Use bot commands instead (see "
        "[CONTRIBUTING.md](https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/blob/main/CONTRIBUTING.md) "
        "for details).\n\n"
        "This issue tracks the round-robin assignment of reviewers for coding guidelines.\n\n"
        "### Current State\n\n"
    )


def split_state_issue_body(body: str) -> StateIssueBodyParts:
    if not body:
        return StateIssueBodyParts(
            prefix=default_state_issue_prefix(),
            state_block_inner=None,
            between_state_and_lock="\n\n",
            lock_block_inner=None,
            suffix="\n",
            has_state_markers=False,
            has_lock_markers=False,
        )

    state_start = body.find(STATE_BLOCK_START_MARKER)
    state_end = body.find(STATE_BLOCK_END_MARKER)
    lock_start = body.find(LOCK_BLOCK_START_MARKER)
    lock_end = body.find(LOCK_BLOCK_END_MARKER)

    has_state_markers = state_start >= 0 and state_end > state_start
    has_lock_markers = lock_start >= 0 and lock_end > lock_start

    if has_state_markers and has_lock_markers and state_end < lock_start:
        return StateIssueBodyParts(
            prefix=body[:state_start],
            state_block_inner=body[state_start + len(STATE_BLOCK_START_MARKER) : state_end],
            between_state_and_lock=body[state_end + len(STATE_BLOCK_END_MARKER) : lock_start],
            lock_block_inner=body[lock_start + len(LOCK_BLOCK_START_MARKER) : lock_end],
            suffix=body[lock_end + len(LOCK_BLOCK_END_MARKER) :],
            has_state_markers=True,
            has_lock_markers=True,
        )

    return StateIssueBodyParts(
        prefix=default_state_issue_prefix(),
        state_block_inner=None,
        between_state_and_lock="\n\n",
        lock_block_inner=None,
        suffix="\n",
        has_state_markers=False,
        has_lock_markers=False,
    )


def extract_fenced_block(inner_block: str, language_pattern: str) -> str | None:
    if not inner_block:
        return None

    match = re.search(rf"```(?:{language_pattern})\n(.*?)\n```", inner_block, re.DOTALL)
    if match:
        return match.group(1)
    return None


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


def parse_state_yaml_from_issue_body(body: str) -> dict:
    parts = split_state_issue_body(body)

    yaml_content = None
    if parts.has_state_markers and parts.state_block_inner is not None:
        yaml_content = extract_fenced_block(parts.state_block_inner, "ya?ml")

    if yaml_content is None:
        yaml_match = re.search(r"```ya?ml\n(.*?)\n```", body, re.DOTALL)
        if yaml_match:
            yaml_content = yaml_match.group(1)
        else:
            yaml_content = body

    try:
        state = yaml.safe_load(yaml_content) or {}
    except yaml.YAMLError as exc:
        print(f"WARNING: Failed to parse state YAML: {exc}", file=sys.stderr)
        state = {}

    if not isinstance(state, dict):
        return {}
    return state


def parse_lock_metadata_from_issue_body(body: str) -> dict:
    parts = split_state_issue_body(body)
    if not parts.has_lock_markers or parts.lock_block_inner is None:
        return normalize_lock_metadata(None)

    lock_json = extract_fenced_block(parts.lock_block_inner, "json")
    if lock_json is None:
        return normalize_lock_metadata(None)

    try:
        parsed = json.loads(lock_json)
    except json.JSONDecodeError as exc:
        print(f"WARNING: Failed to parse lock metadata JSON: {exc}", file=sys.stderr)
        return normalize_lock_metadata(None)

    if not isinstance(parsed, dict):
        return normalize_lock_metadata(None)

    return normalize_lock_metadata(parsed)


def render_marked_fenced_block(start_marker: str, end_marker: str, language: str, content: str) -> str:
    normalized = content.rstrip("\n")
    return f"{start_marker}\n```{language}\n{normalized}\n```\n{end_marker}"


def render_state_issue_body(
    state: dict,
    lock_meta: dict,
    base_body: str | None = None,
    *,
    preserve_state_block: bool = False,
) -> str:
    parts = split_state_issue_body(base_body or "")

    if preserve_state_block and parts.has_state_markers and parts.state_block_inner is not None:
        state_section = f"{STATE_BLOCK_START_MARKER}{parts.state_block_inner}{STATE_BLOCK_END_MARKER}"
    else:
        yaml_content = yaml.dump(
            state,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        state_section = render_marked_fenced_block(
            STATE_BLOCK_START_MARKER,
            STATE_BLOCK_END_MARKER,
            "yaml",
            yaml_content,
        )

    lock_json = json.dumps(normalize_lock_metadata(lock_meta), indent=2, sort_keys=False)
    lock_section = render_marked_fenced_block(
        LOCK_BLOCK_START_MARKER,
        LOCK_BLOCK_END_MARKER,
        "json",
        lock_json,
    )

    prefix = parts.prefix or default_state_issue_prefix()
    between = parts.between_state_and_lock if parts.has_state_markers and parts.has_lock_markers else "\n\n"
    suffix = parts.suffix if parts.has_lock_markers else "\n"

    return f"{prefix}{state_section}{between}{lock_section}{suffix}"


def parse_state_from_issue(issue: dict) -> dict:
    body = issue.get("body", "") or ""
    return parse_state_yaml_from_issue_body(body)


def get_state_issue_snapshot(bot) -> StateIssueSnapshot | None:
    state_issue_number = getattr(bot, "STATE_ISSUE_NUMBER", STATE_ISSUE_NUMBER)
    if not state_issue_number:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return None

    response = bot.github_api_request(
        "GET",
        f"issues/{state_issue_number}",
        suppress_error_log=True,
    )
    if response.status_code != 200:
        print(
            "ERROR: Failed to fetch state issue "
            f"#{state_issue_number} (status {response.status_code}): {response.text}",
            file=sys.stderr,
        )
        return None

    if not isinstance(response.payload, dict):
        print("ERROR: State issue response payload was not an object", file=sys.stderr)
        return None

    body = response.payload.get("body")
    if not isinstance(body, str):
        body = ""

    html_url = response.payload.get("html_url")
    if not isinstance(html_url, str) or not html_url:
        repo = f"{__import__('os').environ.get('REPO_OWNER', '')}/{__import__('os').environ.get('REPO_NAME', '')}".strip("/")
        html_url = f"https://github.com/{repo}/issues/{state_issue_number}" if repo else ""

    return StateIssueSnapshot(body=body, etag=response.headers.get("etag"), html_url=html_url)


def conditional_patch_state_issue(bot, body: str, etag: str | None = None):
    state_issue_number = getattr(bot, "STATE_ISSUE_NUMBER", STATE_ISSUE_NUMBER)
    return bot.github_api_request(
        "PATCH",
        f"issues/{state_issue_number}",
        {"body": body},
        suppress_error_log=True,
    )


def assert_lock_held(bot, operation: str) -> None:
    if bot.ACTIVE_LEASE_CONTEXT is None:
        raise RuntimeError(f"Mutating path reached without lease lock: {operation}")


def load_state(bot, *, fail_on_unavailable: bool = False) -> dict:
    default_state = {
        "last_updated": None,
        "current_index": 0,
        "queue": [],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},
    }

    issue = bot.get_state_issue()
    if not issue:
        if fail_on_unavailable:
            raise RuntimeError(
                "State issue is unavailable for a mutating event; refusing to continue "
                "with fallback defaults."
            )
        print("WARNING: Could not fetch state issue, using defaults", file=sys.stderr)
        return default_state

    state = parse_state_from_issue(issue)
    if state.get("last_updated") is None:
        state["last_updated"] = None
    if not isinstance(state.get("current_index"), int):
        state["current_index"] = 0
    if not isinstance(state.get("queue"), list):
        state["queue"] = []
    if not isinstance(state.get("pass_until"), list):
        state["pass_until"] = []
    if not isinstance(state.get("recent_assignments"), list):
        state["recent_assignments"] = []
    if not isinstance(state.get("active_reviews"), dict):
        state["active_reviews"] = {}
    return state


def save_state(bot, state: dict) -> bool:
    assert_lock_held(bot, "save_state")

    state_issue_number = getattr(bot, "STATE_ISSUE_NUMBER", STATE_ISSUE_NUMBER)
    lock_api_retry_limit = getattr(bot, "LOCK_API_RETRY_LIMIT", LOCK_API_RETRY_LIMIT)
    lock_retry_base_seconds = getattr(bot, "LOCK_RETRY_BASE_SECONDS", LOCK_RETRY_BASE_SECONDS)

    if not state_issue_number:
        print("ERROR: STATE_ISSUE_NUMBER not set", file=sys.stderr)
        return False

    state["last_updated"] = datetime.now(timezone.utc).isoformat()

    for attempt in range(1, lock_api_retry_limit + 1):
        if not bot.ensure_state_issue_lease_lock_fresh():
            print("ERROR: Failed to refresh reviewer-bot lease lock before save", file=sys.stderr)
            return False

        snapshot = bot.get_state_issue_snapshot()
        if snapshot is None:
            return False

        lock_meta = bot.parse_lock_metadata_from_issue_body(snapshot.body)
        body = bot.render_state_issue_body(state, lock_meta, snapshot.body)

        response = bot.conditional_patch_state_issue(body, snapshot.etag)
        if response.status_code == 200:
            print(f"State saved to issue #{state_issue_number}")
            return True

        if response.status_code in {409, 412}:
            print(
                "WARNING: State save hit conflict "
                f"(status {response.status_code}); retrying ({attempt}/{lock_api_retry_limit})",
                file=sys.stderr,
            )
            delay = lock_retry_base_seconds + random.uniform(0, lock_retry_base_seconds)
            time.sleep(delay)
            continue

        if response.status_code == 404:
            print(
                f"ERROR: State issue #{state_issue_number} not found during save_state",
                file=sys.stderr,
            )
            return False

        if response.status_code in {401, 403}:
            print(
                "ERROR: Permission failure while saving state issue "
                f"#{state_issue_number} (status {response.status_code}): {response.text}",
                file=sys.stderr,
            )
            return False

        if response.status_code == 429 or response.status_code >= 500:
            if attempt < lock_api_retry_limit:
                delay = lock_retry_base_seconds + random.uniform(0, lock_retry_base_seconds)
                print(
                    "WARNING: Retryable state issue write failure "
                    f"(status {response.status_code}); retrying ({attempt}/{lock_api_retry_limit})",
                    file=sys.stderr,
                )
                time.sleep(delay)
                continue
            print(
                "ERROR: Exhausted retries while saving state issue "
                f"#{state_issue_number}; last status {response.status_code}: {response.text}",
                file=sys.stderr,
            )
            return False

        print(
            f"ERROR: Unexpected status {response.status_code} while saving state issue: {response.text}",
            file=sys.stderr,
        )
        return False

    print(f"ERROR: Failed to save state to issue #{state_issue_number} after retries", file=sys.stderr)
    return False


def parse_iso8601_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
