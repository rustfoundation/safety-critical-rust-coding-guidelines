"""Reviewer-bot lease lock helpers."""

from datetime import datetime, timezone
from typing import Any

from . import lock_codec, retrying
from .config import (
    LOCK_REF_NAME,
    LeaseContext,
)
from .runtime_protocols import LeaseLockContext, LeaseLockRuntimeContext


def _log(bot: LeaseLockRuntimeContext, level: str, message: str, **fields: Any) -> None:
    bot.logger.event(level, message, **fields)


def _sleep(bot: LeaseLockRuntimeContext, seconds: float) -> None:
    bot.sleeper.sleep(seconds)


def _jitter(bot: LeaseLockRuntimeContext, lower: float, upper: float) -> float:
    return bot.jitter.uniform(lower, upper)


def _retry_delay(bot: LeaseLockRuntimeContext, base_seconds: float, retry_attempt: int) -> float:
    class _BotJitter:
        def uniform(self, lower: float, upper: float) -> float:
            return _jitter(bot, lower, upper)

    return retrying.bounded_exponential_delay(
        base_seconds,
        retry_attempt,
        jitter=_BotJitter(),
    )


def _now(bot: LeaseLockRuntimeContext) -> datetime:
    return bot.clock.now()


def _monotonic(bot: LeaseLockRuntimeContext) -> float:
    return bot.time.monotonic()


def _uuid4_hex(bot: LeaseLockRuntimeContext) -> str:
    return bot.uuid_source.uuid4_hex()


def _lock_lease_ttl_seconds(bot: LeaseLockRuntimeContext) -> int:
    return bot.lock_lease_ttl_seconds()


def _lock_api_retry_limit(bot: LeaseLockRuntimeContext) -> int:
    return bot.lock_api_retry_limit()


def _lock_retry_base_seconds(bot: LeaseLockRuntimeContext) -> float:
    return bot.lock_retry_base_seconds()


def _lock_max_wait_seconds(bot: LeaseLockRuntimeContext) -> int:
    return bot.lock_max_wait_seconds()


def _lock_renewal_window_seconds(bot: LeaseLockRuntimeContext) -> int:
    return bot.lock_renewal_window_seconds()


def lock_is_currently_valid(bot: LeaseLockContext, lock_meta: dict, now: datetime | None = None) -> bool:
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
    now = now or _now(bot)
    return expires_at > now


def get_lock_owner_context(bot: LeaseLockContext) -> tuple[str, str, str]:
    run_id = (
        bot.get_config_value("WORKFLOW_RUN_ID", "").strip()
        or bot.get_config_value("GITHUB_RUN_ID", "").strip()
        or "local-run"
    )
    workflow = (
        bot.get_config_value("WORKFLOW_NAME", "").strip()
        or bot.get_config_value("GITHUB_WORKFLOW", "").strip()
        or "reviewer-bot"
    )
    job = (
        bot.get_config_value("WORKFLOW_JOB_NAME", "").strip()
        or bot.get_config_value("GITHUB_JOB", "").strip()
        or "reviewer-bot"
    )
    return run_id, workflow, job


def build_lock_metadata(bot: LeaseLockContext, lock_token: str, lock_owner_run_id: str, lock_owner_workflow: str, lock_owner_job: str) -> dict:
    acquired_at = _now(bot)
    expires_at = acquired_at.timestamp() + _lock_lease_ttl_seconds(bot)
    return lock_codec.normalize_lock_metadata(
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


def clear_lock_metadata(bot: LeaseLockContext) -> dict:
    return lock_codec.normalize_lock_metadata({"lock_state": "unlocked"})


def normalize_lock_ref_name(ref_name: str) -> str:
    normalized = ref_name.strip()
    if normalized.startswith("refs/"):
        normalized = normalized[len("refs/") :]
    if not normalized:
        normalized = LOCK_REF_NAME
    return normalized


def get_lock_ref_name(bot: LeaseLockContext) -> str:
    return normalize_lock_ref_name(bot.lock_ref_name())


def get_lock_ref_display(bot: LeaseLockContext) -> str:
    return f"refs/{get_lock_ref_name(bot)}"


def get_state_issue_html_url(bot: LeaseLockContext) -> str:
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


def _snapshot_matches_expected_lock(current_lock: dict, expected_token: str) -> bool:
    return (
        isinstance(current_lock, dict)
        and current_lock.get("lock_state") == "locked"
        and current_lock.get("lock_token") == expected_token
    )


def _snapshot_matches_expected_owner(current_lock: dict, run_id: str, workflow: str, job: str) -> bool:
    return (
        isinstance(current_lock, dict)
        and str(current_lock.get("lock_owner_run_id") or "") == run_id
        and str(current_lock.get("lock_owner_workflow") or "") == workflow
        and str(current_lock.get("lock_owner_job") or "") == job
    )


def _activate_lease_context(
    bot: LeaseLockContext,
    lock_token: str,
    lock_owner_run_id: str,
    lock_owner_workflow: str,
    lock_owner_job: str,
    lock_expires_at: str | None,
) -> LeaseContext:
    bot.ACTIVE_LEASE_CONTEXT = LeaseContext(
        lock_token=lock_token,
        lock_owner_run_id=lock_owner_run_id,
        lock_owner_workflow=lock_owner_workflow,
        lock_owner_job=lock_owner_job,
        state_issue_url=bot.get_state_issue_html_url(),
        lock_ref=bot.get_lock_ref_display(),
        lock_expires_at=lock_expires_at,
    )
    _log(
        bot,
        "info",
        "Acquired reviewer-bot lease lock",
        run_id=lock_owner_run_id,
        token_prefix=lock_token[:8],
        lock_ref=bot.get_lock_ref_display(),
    )
    return bot.ACTIVE_LEASE_CONTEXT


def _snapshot_is_stale_unlocked_predecessor(current_lock: dict) -> bool:
    return (
        isinstance(current_lock, dict)
        and current_lock.get("lock_state") == "unlocked"
        and current_lock.get("lock_token") is None
    )


def render_lock_commit_message(bot: LeaseLockContext, lock_meta: dict) -> str:
    del bot
    return lock_codec.render_lock_commit_message(lock_meta)


def parse_lock_metadata_from_lock_commit_message(bot: LeaseLockContext, message: str) -> dict:
    del bot
    return lock_codec.parse_lock_commit_message(message)


def ensure_lock_ref_exists(bot: LeaseLockContext) -> str:
    lock_ref = get_lock_ref_name(bot)
    response = bot.github_api_request(
        "GET",
        f"git/ref/{lock_ref}",
        retry_policy="idempotent_read",
        suppress_error_log=True,
    )
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

    default_branch = bot.lock_ref_bootstrap_branch()
    branch_response = bot.github_api_request(
        "GET",
        f"git/ref/heads/{default_branch}",
        retry_policy="idempotent_read",
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

    refresh_response = bot.github_api_request(
        "GET",
        f"git/ref/{lock_ref}",
        retry_policy="idempotent_read",
        suppress_error_log=True,
    )
    if refresh_response.status_code != 200:
        raise RuntimeError(
            "Unable to read reviewer-bot lock ref after create "
            f"(status {refresh_response.status_code}): {refresh_response.text}"
        )

    ref_sha = extract_ref_sha(refresh_response.payload)
    if not ref_sha:
        raise RuntimeError("Reviewer-bot lock ref exists but SHA was missing")
    return ref_sha


def get_lock_ref_snapshot(bot: LeaseLockContext) -> tuple[str, str, dict]:
    ref_sha = ensure_lock_ref_exists(bot)
    commit_response = bot.github_api_request(
        "GET",
        f"git/commits/{ref_sha}",
        retry_policy="idempotent_read",
        suppress_error_log=True,
    )
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


def create_lock_commit(bot: LeaseLockContext, parent_sha: str, tree_sha: str, lock_meta: dict):
    return bot.github_api_request(
        "POST",
        "git/commits",
        {"message": render_lock_commit_message(bot, lock_meta), "tree": tree_sha, "parents": [parent_sha]},
        suppress_error_log=True,
    )


def cas_update_lock_ref(bot: LeaseLockContext, new_sha: str):
    return bot.github_api_request(
        "PATCH",
        f"git/refs/{get_lock_ref_name(bot)}",
        {"sha": new_sha, "force": False},
        suppress_error_log=True,
    )


def ensure_state_issue_lease_lock_fresh(bot: LeaseLockContext) -> bool:
    context = bot.ACTIVE_LEASE_CONTEXT
    if context is None:
        return False
    if not context.lock_expires_at:
        return True
    expires_at = bot.parse_iso8601_timestamp(context.lock_expires_at)
    if expires_at is None:
        return bot.renew_state_issue_lease_lock(context)
    remaining_seconds = (expires_at - _now(bot)).total_seconds()
    renewal_window = _lock_renewal_window_seconds(bot)
    if remaining_seconds > renewal_window:
        return True
    _log(
        bot,
        "info",
        "Reviewer-bot lease lock nearing expiry; attempting renewal",
        remaining_seconds=int(remaining_seconds),
        token_prefix=context.lock_token[:8],
    )
    return bot.renew_state_issue_lease_lock(context)


def renew_state_issue_lease_lock(bot: LeaseLockContext, context: LeaseContext) -> bool:
    retry_limit = _lock_api_retry_limit(bot)
    retry_base = _lock_retry_base_seconds(bot)
    for attempt in range(1, retry_limit + 1):
        try:
            ref_head_sha, tree_sha, current_lock = bot.get_lock_ref_snapshot()
        except RuntimeError as exc:
            _log(bot, "error", f"Failed to read lock snapshot during renewal: {exc}")
            return False
        current_token = current_lock.get("lock_token")
        if current_token != context.lock_token:
            _log(
                bot,
                "error",
                "Cannot renew reviewer-bot lock due to token mismatch",
                expected_prefix=context.lock_token[:8],
                actual_prefix=str(current_token)[:8],
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
            if retrying.is_retryable_status(create_response.status_code):
                delay = _retry_delay(bot, retry_base, attempt)
                _log(
                    bot,
                    "warning",
                    "Retryable lease lock renewal commit failure",
                    status_code=create_response.status_code,
                    retry_attempt=attempt,
                    retry_limit=retry_limit,
                )
                _sleep(bot, delay)
                continue
            _log(
                bot,
                "error",
                f"Failed to create lock renewal commit (status {create_response.status_code}): {create_response.text}",
                status_code=create_response.status_code,
            )
            return False
        new_commit_sha = extract_commit_sha(create_response.payload)
        if not new_commit_sha:
            _log(bot, "error", "Lock renewal commit response missing SHA")
            return False
        update_response = bot.cas_update_lock_ref(new_commit_sha)
        if update_response.status_code == 200:
            context.lock_expires_at = desired_lock.get("lock_expires_at")
            _log(
                bot,
                "info",
                "Renewed reviewer-bot lease lock",
                run_id=context.lock_owner_run_id,
                token_prefix=context.lock_token[:8],
            )
            return True
        if update_response.status_code in {409, 422} or retrying.is_retryable_status(update_response.status_code):
            delay = _retry_delay(bot, retry_base, attempt)
            _log(
                bot,
                "warning",
                "Retryable lease lock renewal ref update failure",
                status_code=update_response.status_code,
                retry_attempt=attempt,
                retry_limit=retry_limit,
            )
            _sleep(bot, delay)
            continue
        _log(
            bot,
            "error",
            f"Failed to update lock ref during renewal (status {update_response.status_code}): {update_response.text}",
            status_code=update_response.status_code,
        )
        return False
    _log(bot, "error", "Exhausted retries while renewing reviewer-bot lease lock")
    return False


def acquire_state_issue_lease_lock(bot: LeaseLockContext) -> LeaseContext:
    if bot.ACTIVE_LEASE_CONTEXT is not None:
        return bot.ACTIVE_LEASE_CONTEXT
    lock_token = _uuid4_hex(bot)
    lock_owner_run_id, lock_owner_workflow, lock_owner_job = get_lock_owner_context(bot)
    wait_started_at = _monotonic(bot)
    attempt = 0
    max_wait = _lock_max_wait_seconds(bot)
    retry_base = _lock_retry_base_seconds(bot)
    while True:
        attempt += 1
        elapsed = _monotonic(bot) - wait_started_at
        if elapsed > max_wait:
            raise RuntimeError(
                "Timed out waiting for reviewer-bot lease lock "
                f"after {int(elapsed)}s (run_id={lock_owner_run_id}, token_prefix={lock_token[:8]}, "
                f"lock_ref={bot.get_lock_ref_display()})"
            )
        ref_head_sha, tree_sha, current_lock = bot.get_lock_ref_snapshot()
        now = _now(bot)
        lock_valid = bot.lock_is_currently_valid(current_lock, now)
        if lock_valid and _snapshot_matches_expected_lock(current_lock, lock_token):
            if not _snapshot_matches_expected_owner(
                current_lock, lock_owner_run_id, lock_owner_workflow, lock_owner_job
            ):
                raise RuntimeError(
                    "Lease lock token matches current run but owner metadata drifted; failing closed "
                    f"(token_prefix={lock_token[:8]})"
                )
            return _activate_lease_context(
                bot,
                lock_token,
                lock_owner_run_id,
                lock_owner_workflow,
                lock_owner_job,
                current_lock.get("lock_expires_at") if isinstance(current_lock, dict) else None,
            )
        if not lock_valid:
            desired_lock = bot.build_lock_metadata(
                lock_token, lock_owner_run_id, lock_owner_workflow, lock_owner_job
            )
            create_response = bot.create_lock_commit(ref_head_sha, tree_sha, desired_lock)
            if create_response.status_code != 201:
                if retrying.is_retryable_status(create_response.status_code):
                    _log(
                        bot,
                        "warning",
                        "Retryable lease lock acquire commit failure",
                        status_code=create_response.status_code,
                        retry_attempt=attempt,
                    )
                    delay = _retry_delay(bot, retry_base, attempt)
                    _sleep(bot, delay)
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
                snapshot_ref_sha, snapshot_tree_sha, snapshot_lock = bot.get_lock_ref_snapshot()
                del snapshot_ref_sha, snapshot_tree_sha
                if _snapshot_matches_expected_lock(snapshot_lock, lock_token):
                    if not _snapshot_matches_expected_owner(
                        snapshot_lock, lock_owner_run_id, lock_owner_workflow, lock_owner_job
                    ):
                        raise RuntimeError(
                            "Lease lock acquire confirmed expected token with mismatched owner metadata "
                            f"(token_prefix={lock_token[:8]})"
                        )
                    return _activate_lease_context(
                        bot,
                        lock_token,
                        lock_owner_run_id,
                        lock_owner_workflow,
                        lock_owner_job,
                        desired_lock.get("lock_expires_at"),
                    )
                if _snapshot_is_stale_unlocked_predecessor(snapshot_lock):
                    _log(
                        bot,
                        "warning",
                        "Lease lock acquire visibility lag detected; retrying confirmation",
                        retry_attempt=attempt,
                        token_prefix=lock_token[:8],
                    )
                    delay = _retry_delay(bot, retry_base, attempt)
                    _sleep(bot, delay)
                    continue
                conflicting_token = snapshot_lock.get("lock_token") if isinstance(snapshot_lock, dict) else None
                raise RuntimeError(
                    "Lease lock acquire confirmed unexpected lock state after ref update "
                    f"(expected prefix={lock_token[:8]}, got prefix={str(conflicting_token)[:8]})"
                )
            if update_response.status_code in {409, 422}:
                _log(bot, "warning", "Lease lock acquire conflict", status_code=update_response.status_code, retry_attempt=attempt)
            elif update_response.status_code == 404:
                raise RuntimeError(f"Lock ref {bot.get_lock_ref_display()} not found while acquiring lease lock")
            elif update_response.status_code in {401, 403}:
                raise RuntimeError(
                    "Insufficient permission to acquire reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}"
                )
            elif retrying.is_retryable_status(update_response.status_code):
                _log(bot, "warning", "Retryable lease lock acquire failure", status_code=update_response.status_code, retry_attempt=attempt)
            else:
                raise RuntimeError(
                    "Unexpected status while acquiring reviewer-bot lease lock "
                    f"(status {update_response.status_code}): {update_response.text}"
                )
        else:
            lock_owner = current_lock.get("lock_owner_run_id") or "unknown"
            lock_expires_at = current_lock.get("lock_expires_at") or "unknown"
            _log(
                bot,
                "info",
                "Reviewer-bot lease lock currently held; waiting",
                lock_owner=lock_owner,
                lock_expires_at=lock_expires_at,
                lock_ref=bot.get_lock_ref_display(),
            )
        delay = _retry_delay(bot, retry_base, attempt)
        _sleep(bot, delay)


def release_state_issue_lease_lock(bot: LeaseLockContext) -> bool:
    context = bot.ACTIVE_LEASE_CONTEXT
    if context is None:
        return True
    released = False
    retry_limit = _lock_api_retry_limit(bot)
    retry_base = _lock_retry_base_seconds(bot)
    try:
        for attempt in range(1, retry_limit + 1):
            try:
                ref_head_sha, tree_sha, current_lock = bot.get_lock_ref_snapshot()
            except RuntimeError as exc:
                _log(bot, "error", f"Failed to read lock snapshot while releasing lock: {exc}")
                break
            current_token = current_lock.get("lock_token")
            if current_token != context.lock_token:
                if _snapshot_is_stale_unlocked_predecessor(current_lock):
                    _log(
                        bot,
                        "warning",
                        "Lease lock release observed stale unlocked predecessor; retrying",
                        retry_attempt=attempt,
                        token_prefix=context.lock_token[:8],
                    )
                    delay = _retry_delay(bot, retry_base, attempt)
                    _sleep(bot, delay)
                    continue
                _log(
                    bot,
                    "warning",
                    "Lease lock token mismatch during release",
                    expected_prefix=context.lock_token[:8],
                    actual_prefix=str(current_token)[:8],
                )
                return False
            create_response = bot.create_lock_commit(ref_head_sha, tree_sha, bot.clear_lock_metadata())
            if create_response.status_code != 201:
                if retrying.is_retryable_status(create_response.status_code):
                    _log(
                        bot,
                        "warning",
                        "Retryable lease lock release commit failure",
                        status_code=create_response.status_code,
                        retry_attempt=attempt,
                        retry_limit=retry_limit,
                    )
                    delay = _retry_delay(bot, retry_base, attempt)
                    _sleep(bot, delay)
                    continue
                _log(
                    bot,
                    "error",
                    f"Failed to create lock release commit (status {create_response.status_code}): {create_response.text}",
                    status_code=create_response.status_code,
                )
                break
            new_commit_sha = extract_commit_sha(create_response.payload)
            if not new_commit_sha:
                _log(bot, "error", "Lock release commit response missing SHA")
                break
            update_response = bot.cas_update_lock_ref(new_commit_sha)
            if update_response.status_code == 200:
                released = True
                _log(
                    bot,
                    "info",
                    "Released reviewer-bot lease lock",
                    run_id=context.lock_owner_run_id,
                    token_prefix=context.lock_token[:8],
                    lock_ref=bot.get_lock_ref_display(),
                )
                return True
            if update_response.status_code in {409, 422} or retrying.is_retryable_status(update_response.status_code):
                _log(
                    bot,
                    "warning",
                    "Retryable lease lock release failure",
                    status_code=update_response.status_code,
                    retry_attempt=attempt,
                    retry_limit=retry_limit,
                )
                delay = _retry_delay(bot, retry_base, attempt)
                _sleep(bot, delay)
                continue
            if update_response.status_code in {401, 403, 404}:
                _log(
                    bot,
                    "error",
                    f"Hard failure releasing reviewer-bot lease lock (status {update_response.status_code}): {update_response.text}",
                    status_code=update_response.status_code,
                )
                break
            _log(
                bot,
                "error",
                f"Unexpected status while releasing reviewer-bot lease lock (status {update_response.status_code}): {update_response.text}",
                status_code=update_response.status_code,
            )
            break
        return False
    finally:
        if not released:
            _log(
                bot,
                "error",
                "Lease lock release failed",
                run_id=context.lock_owner_run_id,
                token_prefix=context.lock_token[:8],
                state_issue_url=context.state_issue_url,
            )
        bot.ACTIVE_LEASE_CONTEXT = None
