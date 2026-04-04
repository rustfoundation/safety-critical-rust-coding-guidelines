"""State issue parsing, loading, and saving helpers."""

import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

import yaml

from . import retrying
from .config import (
    FRESHNESS_RUNTIME_EPOCH_LEGACY,
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
    STATE_SCHEMA_VERSION,
    StateIssueBodyParts,
    StateIssueSnapshot,
)
from .context import StateStoreContext


def _log(bot: StateStoreContext, level: str, message: str, **fields: Any) -> None:
    logger = getattr(bot, "logger", None)
    if logger is not None and hasattr(logger, "event"):
        logger.event(level, message, **fields)
        return
    sys.stderr.write(f"{message}\n")


def _log_fallback(level: str, message: str) -> None:
    del level
    sys.stderr.write(f"{message}\n")


def _sleep(bot: StateStoreContext, seconds: float) -> None:
    sleeper = getattr(bot, "sleeper", None)
    if sleeper is not None and hasattr(sleeper, "sleep"):
        sleeper.sleep(seconds)
        return
    __import__("time").sleep(seconds)


def _jitter(bot: StateStoreContext, lower: float, upper: float) -> float:
    jitter = getattr(bot, "jitter", None)
    if jitter is not None and hasattr(jitter, "uniform"):
        return jitter.uniform(lower, upper)
    return __import__("random").uniform(lower, upper)


def _retry_delay(bot: StateStoreContext, base_seconds: float, retry_attempt: int) -> float:
    class _BotJitter:
        def uniform(self, lower: float, upper: float) -> float:
            return _jitter(bot, lower, upper)

    return retrying.bounded_exponential_delay(
        base_seconds,
        retry_attempt,
        jitter=_BotJitter(),
    )


def _now_iso(bot: StateStoreContext) -> str:
    clock = getattr(bot, "clock", None)
    if clock is not None and hasattr(clock, "now"):
        return clock.now().isoformat()
    return datetime.now(timezone.utc).isoformat()


def _state_issue_number(bot: StateStoreContext) -> int:
    accessor = getattr(bot, "state_issue_number", None)
    if callable(accessor):
        return accessor()
    return getattr(bot, "STATE_ISSUE_NUMBER", STATE_ISSUE_NUMBER)


def _lock_api_retry_limit(bot: StateStoreContext) -> int:
    accessor = getattr(bot, "lock_api_retry_limit", None)
    if callable(accessor):
        return accessor()
    return getattr(bot, "LOCK_API_RETRY_LIMIT", LOCK_API_RETRY_LIMIT)


def _lock_retry_base_seconds(bot: StateStoreContext) -> float:
    accessor = getattr(bot, "lock_retry_base_seconds", None)
    if callable(accessor):
        return accessor()
    return getattr(bot, "LOCK_RETRY_BASE_SECONDS", LOCK_RETRY_BASE_SECONDS)


def get_state_issue(bot: StateStoreContext) -> dict | None:
    """Fetch the state issue from GitHub with retry for transient failures."""
    state_issue_number = _state_issue_number(bot)
    state_read_retry_limit = getattr(bot, "STATE_READ_RETRY_LIMIT", STATE_READ_RETRY_LIMIT)
    state_read_retry_base_seconds = getattr(
        bot, "STATE_READ_RETRY_BASE_SECONDS", STATE_READ_RETRY_BASE_SECONDS
    )

    if not state_issue_number:
        _log(bot, "error", "STATE_ISSUE_NUMBER not set")
        return None

    for attempt in range(1, state_read_retry_limit + 1):
        response = bot.github_api_request(
            "GET",
            f"issues/{state_issue_number}",
            suppress_error_log=True,
        )

        if response.status_code == 200:
            if not isinstance(response.payload, dict):
                _log(bot, "error", "State issue response payload was not an object")
                return None
            return response.payload

        if response.status_code in {401, 403, 404}:
            _log(
                bot,
                "error",
                f"Failed to fetch state issue #{state_issue_number} (status {response.status_code}): {response.text}",
                state_issue_number=state_issue_number,
                status_code=response.status_code,
            )
            return None

        if retrying.is_retryable_status(response.status_code):
            if attempt < state_read_retry_limit:
                delay = _retry_delay(bot, state_read_retry_base_seconds, attempt)
                _log(
                    bot,
                    "warning",
                    f"Retryable state issue read failure (status {response.status_code}); retrying ({attempt}/{state_read_retry_limit})",
                    state_issue_number=state_issue_number,
                    status_code=response.status_code,
                    retry_attempt=attempt,
                )
                _sleep(bot, delay)
                continue
            _log(
                bot,
                "error",
                f"Exhausted retries while fetching state issue #{state_issue_number}; last status {response.status_code}: {response.text}",
                state_issue_number=state_issue_number,
                status_code=response.status_code,
            )
            return None

        _log(
            bot,
            "error",
            f"Unexpected status while fetching state issue #{state_issue_number}: {response.status_code} {response.text}",
            state_issue_number=state_issue_number,
            status_code=response.status_code,
        )
        return None

    _log(bot, "error", f"Failed to fetch state issue #{state_issue_number} after retries", state_issue_number=state_issue_number)
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
        _log_fallback("warning", f"Failed to parse state YAML: {exc}")
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
        _log_fallback("warning", f"Failed to parse lock metadata JSON: {exc}")
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


def get_state_issue_snapshot(bot: StateStoreContext) -> StateIssueSnapshot | None:
    state_issue_number = _state_issue_number(bot)
    if not state_issue_number:
        _log(bot, "error", "STATE_ISSUE_NUMBER not set")
        return None

    response = bot.github_api_request(
        "GET",
        f"issues/{state_issue_number}",
        retry_policy="idempotent_read",
        suppress_error_log=True,
    )
    if response.status_code != 200:
        _log(
            bot,
            "error",
            f"Failed to fetch state issue #{state_issue_number} (status {response.status_code}): {response.text}",
            state_issue_number=state_issue_number,
            status_code=response.status_code,
        )
        return None

    if not isinstance(response.payload, dict):
        _log(bot, "error", "State issue response payload was not an object")
        return None

    body = response.payload.get("body")
    if not isinstance(body, str):
        body = ""

    html_url = response.payload.get("html_url")
    if not isinstance(html_url, str) or not html_url:
        repo = f"{bot.get_config_value('REPO_OWNER', '')}/{bot.get_config_value('REPO_NAME', '')}".strip("/")
        html_url = f"https://github.com/{repo}/issues/{state_issue_number}" if repo else ""

    return StateIssueSnapshot(body=body, etag=response.headers.get("etag"), html_url=html_url)


def conditional_patch_state_issue(bot: StateStoreContext, body: str, etag: str | None = None):
    state_issue_number = _state_issue_number(bot)
    extra_headers = {"If-Match": etag} if isinstance(etag, str) and etag else None
    return bot.github_api_request(
        "PATCH",
        f"issues/{state_issue_number}",
        {"body": body},
        extra_headers=extra_headers,
        suppress_error_log=True,
    )


def assert_lock_held(bot: StateStoreContext, operation: str) -> None:
    if bot.ACTIVE_LEASE_CONTEXT is None:
        raise RuntimeError(f"Mutating path reached without lease lock: {operation}")


def load_state(bot: StateStoreContext, *, fail_on_unavailable: bool = False) -> dict:
    default_state = {
        "schema_version": STATE_SCHEMA_VERSION,
        "freshness_runtime_epoch": FRESHNESS_RUNTIME_EPOCH_LEGACY,
        "status_projection_epoch": None,
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
        _log(bot, "warning", "Could not fetch state issue, using defaults")
        return default_state

    state = parse_state_from_issue(issue)
    if not isinstance(state.get("schema_version"), int):
        state["schema_version"] = STATE_SCHEMA_VERSION
    if not isinstance(state.get("freshness_runtime_epoch"), str) or not state.get("freshness_runtime_epoch"):
        state["freshness_runtime_epoch"] = FRESHNESS_RUNTIME_EPOCH_LEGACY
    if not isinstance(state.get("status_projection_epoch"), str) or not state.get("status_projection_epoch"):
        state["status_projection_epoch"] = None
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


def save_state(bot: StateStoreContext, state: dict) -> bool:
    assert_lock_held(bot, "save_state")

    state_issue_number = _state_issue_number(bot)
    lock_api_retry_limit = _lock_api_retry_limit(bot)
    lock_retry_base_seconds = _lock_retry_base_seconds(bot)

    if not state_issue_number:
        _log(bot, "error", "STATE_ISSUE_NUMBER not set")
        return False

    state["last_updated"] = _now_iso(bot)

    for attempt in range(1, lock_api_retry_limit + 1):
        if not bot.ensure_state_issue_lease_lock_fresh():
            _log(bot, "error", "Failed to refresh reviewer-bot lease lock before save")
            return False

        snapshot = bot.get_state_issue_snapshot()
        if snapshot is None:
            return False

        lock_meta = bot.parse_lock_metadata_from_issue_body(snapshot.body)
        body = bot.render_state_issue_body(state, lock_meta, snapshot.body)

        response = bot.conditional_patch_state_issue(body, snapshot.etag)
        if response.status_code == 200:
            _log(bot, "info", f"State saved to issue #{state_issue_number}", state_issue_number=state_issue_number)
            return True

        if response.status_code in {409, 412}:
            _log(
                bot,
                "warning",
                f"State save hit conflict (status {response.status_code}); retrying ({attempt}/{lock_api_retry_limit})",
                state_issue_number=state_issue_number,
                status_code=response.status_code,
                retry_attempt=attempt,
            )
            delay = _retry_delay(bot, lock_retry_base_seconds, attempt)
            _sleep(bot, delay)
            continue

        if response.status_code == 404:
            _log(bot, "error", f"State issue #{state_issue_number} not found during save_state", state_issue_number=state_issue_number)
            return False

        if response.status_code in {401, 403}:
            _log(
                bot,
                "error",
                f"Permission failure while saving state issue #{state_issue_number} (status {response.status_code}): {response.text}",
                state_issue_number=state_issue_number,
                status_code=response.status_code,
            )
            return False

        if retrying.is_retryable_status(response.status_code):
            if attempt < lock_api_retry_limit:
                delay = _retry_delay(bot, lock_retry_base_seconds, attempt)
                _log(
                    bot,
                    "warning",
                    f"Retryable state issue write failure (status {response.status_code}); retrying ({attempt}/{lock_api_retry_limit})",
                    state_issue_number=state_issue_number,
                    status_code=response.status_code,
                    retry_attempt=attempt,
                )
                _sleep(bot, delay)
                continue
            _log(
                bot,
                "error",
                f"Exhausted retries while saving state issue #{state_issue_number}; last status {response.status_code}: {response.text}",
                state_issue_number=state_issue_number,
                status_code=response.status_code,
            )
            return False

        _log(
            bot,
            "error",
            f"Unexpected status {response.status_code} while saving state issue: {response.text}",
            state_issue_number=state_issue_number,
            status_code=response.status_code,
        )
        return False

    _log(bot, "error", f"Failed to save state to issue #{state_issue_number} after retries", state_issue_number=state_issue_number)
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
