"""Reviewer-bot lease lock helpers."""

import json
import os
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from .config import (
    LOCK_API_RETRY_LIMIT,
    LOCK_COMMIT_MARKER,
    LOCK_LEASE_TTL_SECONDS,
    LOCK_MAX_WAIT_SECONDS,
    LOCK_REF_BOOTSTRAP_BRANCH,
    LOCK_REF_NAME,
    LOCK_RENEWAL_WINDOW_SECONDS,
    LOCK_RETRY_BASE_SECONDS,
    LeaseContext,
)
from .context import ReviewerBotContext


def lock_is_currently_valid(bot: ReviewerBotContext, lock_meta: dict, now: datetime | None = None) -> bool:
    if not isinstance(lock_meta, dict):
        return False
    if lock_meta.get("lock_state") != "locked":
        return False
    lock_token = lock_meta.get("lock_token")
    if not isinstance(lock_token, str) or not lock_token:
        return False
    expires_at = bot.parse_iso8601_timestamp(lock_meta.get("lock_expires_at"))
    if expires_at is None:
        return False
    now = now or datetime.now(timezone.utc)
    return expires_at > now


def get_lock_owner_context() -> tuple[str, str, str]:
    run_id = (
        os.environ.get("WORKFLOW_RUN_ID", "").strip()
        or os.environ.get("GITHUB_RUN_ID", "").strip()
        or "local-run"
    )
    workflow = (
        os.environ.get("WORKFLOW_NAME", "").strip()
        or os.environ.get("GITHUB_WORKFLOW", "").strip()
        or "reviewer-bot"
    )
    job = (
        os.environ.get("WORKFLOW_JOB_NAME", "").strip()
        or os.environ.get("GITHUB_JOB", "").strip()
        or "reviewer-bot"
    )
    return run_id, workflow, job


def build_lock_metadata(bot: ReviewerBotContext, lock_token: str, lock_owner_run_id: str, lock_owner_workflow: str, lock_owner_job: str) -> dict:
    acquired_at = datetime.now(timezone.utc)
    expires_at = acquired_at.timestamp() + getattr(bot, "LOCK_LEASE_TTL_SECONDS", LOCK_LEASE_TTL_SECONDS)
    return bot.normalize_lock_metadata(
        {
            "schema_version": 1,
            "lock_state": "locked",
            "lock_owner_run_id": lock_owner_run_id,
            "lock_owner_workflow": lock_owner_workflow,
            "lock_owner_job": lock_owner_job,
            "lock_token": lock_token,
            "lock_acquired_at": acquired_at.isoformat(),
            "lock_expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
        }
    )


def clear_lock_metadata(bot: ReviewerBotContext) -> dict:
    return bot.normalize_lock_metadata({"lock_state": "unlocked"})


def normalize_lock_ref_name(ref_name: str) -> str:
    normalized = ref_name.strip()
    if normalized.startswith("refs/"):
        normalized = normalized[len("refs/") :]
    if not normalized:
        normalized = LOCK_REF_NAME
    return normalized


def get_lock_ref_name(bot: ReviewerBotContext) -> str:
    return normalize_lock_ref_name(getattr(bot, "LOCK_REF_NAME", LOCK_REF_NAME))


def get_lock_ref_display(bot: ReviewerBotContext) -> str:
    return f"refs/{get_lock_ref_name(bot)}"


def get_state_issue_html_url(bot: ReviewerBotContext) -> str:
    context = bot.ACTIVE_LEASE_CONTEXT
    if context and context.state_issue_url:
        return context.state_issue_url
    snapshot = bot.get_state_issue_snapshot()
    return snapshot.html_url if snapshot else ""


def extract_ref_sha(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    obj = payload.get("object")
    if not isinstance(obj, dict):
        return None
    sha = obj.get("sha")
    return sha if isinstance(sha, str) and sha else None


def extract_commit_tree_sha(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    tree = payload.get("tree")
    if not isinstance(tree, dict):
        return None
    sha = tree.get("sha")
    return sha if isinstance(sha, str) and sha else None


def extract_commit_sha(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    sha = payload.get("sha")
    return sha if isinstance(sha, str) and sha else None


def render_lock_commit_message(bot: ReviewerBotContext, lock_meta: dict) -> str:
    lock_json = json.dumps(bot.normalize_lock_metadata(lock_meta), sort_keys=False)
    return f"{LOCK_COMMIT_MARKER}\n{lock_json}"


def parse_lock_metadata_from_lock_commit_message(bot: ReviewerBotContext, message: str) -> dict:
    if not message.startswith(f"{LOCK_COMMIT_MARKER}\n"):
        return bot.clear_lock_metadata()
    lock_json = message.split("\n", 1)[1]
    try:
        parsed = json.loads(lock_json)
    except json.JSONDecodeError:
        return bot.clear_lock_metadata()
    return bot.normalize_lock_metadata(parsed if isinstance(parsed, dict) else None)


def ensure_lock_ref_exists(bot: ReviewerBotContext) -> str:
    lock_ref = get_lock_ref_name(bot)
    response = bot.github_api_request("GET", f"git/ref/{lock_ref}", suppress_error_log=True)
    if response.status_code == 200:
        ref_sha = extract_ref_sha(response.payload)
        if not ref_sha:
            raise RuntimeError("Reviewer-bot lock ref exists but SHA was missing")
        return ref_sha
    if response.status_code not in {404, 422}:
        raise RuntimeError(
            "Failed to read reviewer-bot lock ref "
            f"{get_lock_ref_display(bot)} (status {response.status_code}): {response.text}"
        )

    default_branch = getattr(bot, "LOCK_REF_BOOTSTRAP_BRANCH", LOCK_REF_BOOTSTRAP_BRANCH)
    branch_response = bot.github_api_request(
        "GET",
        f"git/ref/heads/{default_branch}",
        suppress_error_log=True,
    )
    if branch_response.status_code != 200:
        raise RuntimeError(
            f"Unable to read bootstrap branch refs/heads/{default_branch} "
            f"for reviewer-bot lock ref create (status {branch_response.status_code}): {branch_response.text}"
        )

    branch_sha = extract_ref_sha(branch_response.payload)
    if not branch_sha:
        raise RuntimeError("Bootstrap branch ref did not include SHA")

    create_response = bot.github_api_request(
        "POST",
        "git/refs",
        {"ref": get_lock_ref_display(bot), "sha": branch_sha},
        suppress_error_log=True,
    )
    if create_response.status_code not in {201, 422}:
        raise RuntimeError(
            "Failed to create reviewer-bot lock ref "
            f"{get_lock_ref_display(bot)} (status {create_response.status_code}): {create_response.text}"
        )

    refresh_response = bot.github_api_request("GET", f"git/ref/{lock_ref}", suppress_error_log=True)
    if refresh_response.status_code != 200:
        raise RuntimeError(
            "Unable to read reviewer-bot lock ref after create "
            f"(status {refresh_response.status_code}): {refresh_response.text}"
        )

    ref_sha = extract_ref_sha(refresh_response.payload)
    if not ref_sha:
        raise RuntimeError("Reviewer-bot lock ref exists but SHA was missing")
    return ref_sha


def get_lock_ref_snapshot(bot: ReviewerBotContext) -> tuple[str, str, dict]:
    ref_sha = ensure_lock_ref_exists(bot)
    commit_response = bot.github_api_request("GET", f"git/commits/{ref_sha}", suppress_error_log=True)
    if commit_response.status_code != 200:
        raise RuntimeError(
            f"Failed to read lock commit {ref_sha} (status {commit_response.status_code}): {commit_response.text}"
        )
    if not isinstance(commit_response.payload, dict):
        raise RuntimeError("Lock commit response payload was not a JSON object")
    tree_sha = extract_commit_tree_sha(commit_response.payload)
    if not tree_sha:
        raise RuntimeError("Lock commit payload missing tree SHA")
    message = commit_response.payload.get("message")
    if not isinstance(message, str):
        message = ""
    lock_meta = parse_lock_metadata_from_lock_commit_message(bot, message)
    return ref_sha, tree_sha, lock_meta


def create_lock_commit(bot: ReviewerBotContext, parent_sha: str, tree_sha: str, lock_meta: dict):
    return bot.github_api_request(
        "POST",
        "git/commits",
        {"message": render_lock_commit_message(bot, lock_meta), "tree": tree_sha, "parents": [parent_sha]},
        suppress_error_log=True,
    )


def cas_update_lock_ref(bot: ReviewerBotContext, new_sha: str):
    return bot.github_api_request(
        "PATCH",
        f"git/refs/{get_lock_ref_name(bot)}",
        {"sha": new_sha, "force": False},
        suppress_error_log=True,
    )


def ensure_state_issue_lease_lock_fresh(bot: ReviewerBotContext) -> bool:
    context = bot.ACTIVE_LEASE_CONTEXT
    if context is None:
        return False
    if not context.lock_expires_at:
        return True
    expires_at = bot.parse_iso8601_timestamp(context.lock_expires_at)
    if expires_at is None:
        return bot.renew_state_issue_lease_lock(context)
    remaining_seconds = (expires_at - datetime.now(timezone.utc)).total_seconds()
    renewal_window = getattr(bot, "LOCK_RENEWAL_WINDOW_SECONDS", LOCK_RENEWAL_WINDOW_SECONDS)
    if remaining_seconds > renewal_window:
        return True
    print(
        "Reviewer-bot lease lock nearing expiry; attempting renewal "
        f"(remaining={int(remaining_seconds)}s, token_prefix={context.lock_token[:8]})"
    )
    return bot.renew_state_issue_lease_lock(context)


def renew_state_issue_lease_lock(bot: ReviewerBotContext, context: LeaseContext) -> bool:
    retry_limit = getattr(bot, "LOCK_API_RETRY_LIMIT", LOCK_API_RETRY_LIMIT)
    retry_base = getattr(bot, "LOCK_RETRY_BASE_SECONDS", LOCK_RETRY_BASE_SECONDS)
    for attempt in range(1, retry_limit + 1):
        try:
            ref_head_sha, tree_sha, current_lock = bot.get_lock_ref_snapshot()
        except RuntimeError as exc:
            print(f"ERROR: Failed to read lock snapshot during renewal: {exc}", file=bot.sys.stderr)
            return False
        current_token = current_lock.get("lock_token")
        if current_token != context.lock_token:
            print(
                "ERROR: Cannot renew reviewer-bot lock due to token mismatch "
                f"(expected prefix={context.lock_token[:8]}, got prefix={str(current_token)[:8]})",
                file=bot.sys.stderr,
            )
            return False
        desired_lock = bot.build_lock_metadata(
            context.lock_token,
            context.lock_owner_run_id,
            context.lock_owner_workflow,
            context.lock_owner_job,
        )
        create_response = bot.create_lock_commit(ref_head_sha, tree_sha, desired_lock)
        if create_response.status_code != 201:
            if create_response.status_code == 429 or create_response.status_code >= 500:
                delay = retry_base + random.uniform(0, retry_base)
                print(
                    "Retryable lease lock renewal commit failure "
                    f"(status {create_response.status_code}); retrying ({attempt}/{retry_limit})",
                    file=bot.sys.stderr,
                )
                time.sleep(delay)
                continue
            print(
                f"ERROR: Failed to create lock renewal commit (status {create_response.status_code}): {create_response.text}",
                file=bot.sys.stderr,
            )
            return False
        new_commit_sha = extract_commit_sha(create_response.payload)
        if not new_commit_sha:
            print("ERROR: Lock renewal commit response missing SHA", file=bot.sys.stderr)
            return False
        update_response = bot.cas_update_lock_ref(new_commit_sha)
        if update_response.status_code == 200:
            context.lock_expires_at = desired_lock.get("lock_expires_at")
            print(
                "Renewed reviewer-bot lease lock "
                f"(run_id={context.lock_owner_run_id}, token_prefix={context.lock_token[:8]})"
            )
            return True
        if update_response.status_code in {409, 422, 429} or update_response.status_code >= 500:
            delay = retry_base + random.uniform(0, retry_base)
            print(
                "Retryable lease lock renewal ref update failure "
                f"(status {update_response.status_code}); retrying ({attempt}/{retry_limit})",
                file=bot.sys.stderr,
            )
            time.sleep(delay)
            continue
        print(
            f"ERROR: Failed to update lock ref during renewal (status {update_response.status_code}): {update_response.text}",
            file=bot.sys.stderr,
        )
        return False
    print("ERROR: Exhausted retries while renewing reviewer-bot lease lock", file=bot.sys.stderr)
    return False


def acquire_state_issue_lease_lock(bot: ReviewerBotContext) -> LeaseContext:
    if bot.ACTIVE_LEASE_CONTEXT is not None:
        return bot.ACTIVE_LEASE_CONTEXT
    lock_token = uuid.uuid4().hex
    lock_owner_run_id, lock_owner_workflow, lock_owner_job = get_lock_owner_context()
    wait_started_at = time.monotonic()
    attempt = 0
    max_wait = getattr(bot, "LOCK_MAX_WAIT_SECONDS", LOCK_MAX_WAIT_SECONDS)
    retry_base = getattr(bot, "LOCK_RETRY_BASE_SECONDS", LOCK_RETRY_BASE_SECONDS)
    while True:
        attempt += 1
        elapsed = time.monotonic() - wait_started_at
        if elapsed > max_wait:
            raise RuntimeError(
                "Timed out waiting for reviewer-bot lease lock "
                f"after {int(elapsed)}s (run_id={lock_owner_run_id}, token_prefix={lock_token[:8]}, "
                f"lock_ref={bot.get_lock_ref_display()})"
            )
        ref_head_sha, tree_sha, current_lock = bot.get_lock_ref_snapshot()
        now = datetime.now(timezone.utc)
        lock_valid = bot.lock_is_currently_valid(current_lock, now)
        if not lock_valid:
            desired_lock = bot.build_lock_metadata(
                lock_token, lock_owner_run_id, lock_owner_workflow, lock_owner_job
            )
            create_response = bot.create_lock_commit(ref_head_sha, tree_sha, desired_lock)
            if create_response.status_code != 201:
                if create_response.status_code == 429 or create_response.status_code >= 500:
                    print(
                        "Retryable lease lock acquire commit failure "
                        f"(status {create_response.status_code}); retrying (attempt {attempt})"
                    )
                    delay = retry_base + random.uniform(0, retry_base)
                    time.sleep(delay)
                    continue
                if create_response.status_code in {401, 403}:
                    raise RuntimeError(
                        "Insufficient permission to create reviewer-bot lock commit "
                        f"(status {create_response.status_code}): {create_response.text}"
                    )
                raise RuntimeError(
                    "Unexpected status while creating reviewer-bot lock commit "
                    f"(status {create_response.status_code}): {create_response.text}"
                )
            new_commit_sha = extract_commit_sha(create_response.payload)
            if not new_commit_sha:
                raise RuntimeError("Lock acquire commit response did not include commit SHA")
            update_response = bot.cas_update_lock_ref(new_commit_sha)
            if update_response.status_code == 200:
                bot.ACTIVE_LEASE_CONTEXT = LeaseContext(
                    lock_token=lock_token,
                    lock_owner_run_id=lock_owner_run_id,
                    lock_owner_workflow=lock_owner_workflow,
                    lock_owner_job=lock_owner_job,
                    state_issue_url=bot.get_state_issue_html_url(),
                    lock_ref=bot.get_lock_ref_display(),
                    lock_expires_at=desired_lock.get("lock_expires_at"),
                )
                print(
                    "Acquired reviewer-bot lease lock "
                    f"(run_id={lock_owner_run_id}, token_prefix={lock_token[:8]}, lock_ref={bot.get_lock_ref_display()})"
                )
                return bot.ACTIVE_LEASE_CONTEXT
            if update_response.status_code in {409, 422}:
                print(
                    "Lease lock acquire conflict "
                    f"(status {update_response.status_code}); retrying (attempt {attempt})"
                )
            elif update_response.status_code == 404:
                raise RuntimeError(f"Lock ref {bot.get_lock_ref_display()} not found while acquiring lease lock")
            elif update_response.status_code in {401, 403}:
                raise RuntimeError(
                    "Insufficient permission to acquire reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}"
                )
            elif update_response.status_code == 429 or update_response.status_code >= 500:
                print(
                    "Retryable lease lock acquire failure "
                    f"(status {update_response.status_code}); retrying (attempt {attempt})"
                )
            else:
                raise RuntimeError(
                    "Unexpected status while acquiring reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}"
                )
        else:
            lock_owner = current_lock.get("lock_owner_run_id") or "unknown"
            lock_expires_at = current_lock.get("lock_expires_at") or "unknown"
            print(
                "Reviewer-bot lease lock currently held by "
                f"run_id={lock_owner} until {lock_expires_at}; waiting (lock_ref={bot.get_lock_ref_display()})"
            )
        delay = retry_base + random.uniform(0, retry_base)
        time.sleep(delay)


def release_state_issue_lease_lock(bot: ReviewerBotContext) -> bool:
    context = bot.ACTIVE_LEASE_CONTEXT
    if context is None:
        return True
    released = False
    retry_limit = getattr(bot, "LOCK_API_RETRY_LIMIT", LOCK_API_RETRY_LIMIT)
    retry_base = getattr(bot, "LOCK_RETRY_BASE_SECONDS", LOCK_RETRY_BASE_SECONDS)
    try:
        for attempt in range(1, retry_limit + 1):
            try:
                ref_head_sha, tree_sha, current_lock = bot.get_lock_ref_snapshot()
            except RuntimeError as exc:
                print(f"ERROR: Failed to read lock snapshot while releasing lock: {exc}", file=bot.sys.stderr)
                break
            current_token = current_lock.get("lock_token")
            if current_token != context.lock_token:
                print(
                    "WARNING: Lease lock token mismatch during release; "
                    f"expected prefix={context.lock_token[:8]}, got prefix={str(current_token)[:8]}",
                    file=bot.sys.stderr,
                )
                return False
            create_response = bot.create_lock_commit(ref_head_sha, tree_sha, bot.clear_lock_metadata())
            if create_response.status_code != 201:
                if create_response.status_code in {429} or create_response.status_code >= 500:
                    print(
                        "Retryable lease lock release commit failure "
                        f"(status {create_response.status_code}); retrying ({attempt}/{retry_limit})",
                        file=bot.sys.stderr,
                    )
                    delay = retry_base + random.uniform(0, retry_base)
                    time.sleep(delay)
                    continue
                print(
                    f"ERROR: Failed to create lock release commit (status {create_response.status_code}): {create_response.text}",
                    file=bot.sys.stderr,
                )
                break
            new_commit_sha = extract_commit_sha(create_response.payload)
            if not new_commit_sha:
                print("ERROR: Lock release commit response missing SHA", file=bot.sys.stderr)
                break
            update_response = bot.cas_update_lock_ref(new_commit_sha)
            if update_response.status_code == 200:
                released = True
                print(
                    "Released reviewer-bot lease lock "
                    f"(run_id={context.lock_owner_run_id}, token_prefix={context.lock_token[:8]}, lock_ref={bot.get_lock_ref_display()})"
                )
                return True
            if update_response.status_code in {409, 422, 429} or update_response.status_code >= 500:
                print(
                    "Retryable lease lock release failure "
                    f"(status {update_response.status_code}); retrying ({attempt}/{retry_limit})",
                    file=bot.sys.stderr,
                )
                delay = retry_base + random.uniform(0, retry_base)
                time.sleep(delay)
                continue
            if update_response.status_code in {401, 403, 404}:
                print(
                    "ERROR: Hard failure releasing reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}",
                    file=bot.sys.stderr,
                )
                break
            print(
                "ERROR: Unexpected status while releasing reviewer-bot lease lock "
                f"(status {update_response.status_code}): {update_response.text}",
                file=bot.sys.stderr,
            )
            break
        return False
    finally:
        if not released:
            print(
                "ERROR: Lease lock release failed "
                f"(run_id={context.lock_owner_run_id}, token_prefix={context.lock_token[:8]}, state_issue_url={context.state_issue_url})",
                file=bot.sys.stderr,
            )
        bot.ACTIVE_LEASE_CONTEXT = None
