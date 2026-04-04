import sys
from types import SimpleNamespace

import pytest

from scripts.reviewer_bot_lib import lease_lock, state_store
from scripts.reviewer_bot_lib.config import GitHubApiResult, LeaseContext
from tests.fixtures.fake_clock import FakeClock
from tests.fixtures.fake_jitter import DeterministicJitter
from tests.fixtures.fake_sleeper import RecordingSleeper
from tests.fixtures.fake_uuid import FixedUuidSource
from tests.fixtures.recording_logger import RecordingLogger


def _lease_bot(**overrides):
    config_values = {
        "WORKFLOW_RUN_ID": "local-run",
        "WORKFLOW_NAME": "reviewer-bot",
        "WORKFLOW_JOB_NAME": "reviewer-bot",
    }
    bot = SimpleNamespace(
        ACTIVE_LEASE_CONTEXT=None,
        LOCK_REF_NAME="heads/reviewer-bot-state-lock",
        LOCK_REF_BOOTSTRAP_BRANCH="main",
        LOCK_API_RETRY_LIMIT=3,
        LOCK_RETRY_BASE_SECONDS=0,
        LOCK_MAX_WAIT_SECONDS=60,
        LOCK_RENEWAL_WINDOW_SECONDS=60,
        sys=sys,
        time=SimpleNamespace(monotonic=lambda: 0.0),
        clock=FakeClock(),
        sleeper=RecordingSleeper(),
        jitter=DeterministicJitter(0.0),
        uuid_source=FixedUuidSource("token-123"),
        logger=RecordingLogger(),
        github_api_request=lambda *args, **kwargs: None,
        get_state_issue_snapshot=lambda: SimpleNamespace(html_url="https://example.com/issues/314"),
        get_config_value=lambda name, default="": config_values.get(name, default),
        normalize_lock_metadata=state_store.normalize_lock_metadata,
        parse_iso8601_timestamp=state_store.parse_iso8601_timestamp,
    )
    for key, value in overrides.items():
        setattr(bot, key, value)
    if "config_values" in overrides:
        config_values.update(overrides["config_values"])
        delattr(bot, "config_values")
    bot.clear_lock_metadata = lambda: lease_lock.clear_lock_metadata(bot)
    bot.get_state_issue_html_url = lambda: lease_lock.get_state_issue_html_url(bot)
    bot.get_lock_ref_display = lambda: lease_lock.get_lock_ref_display(bot)
    bot.get_lock_ref_snapshot = lambda: lease_lock.get_lock_ref_snapshot(bot)
    bot.build_lock_metadata = lambda *args: lease_lock.build_lock_metadata(bot, *args)
    bot.create_lock_commit = lambda parent_sha, tree_sha, lock_meta: lease_lock.create_lock_commit(
        bot, parent_sha, tree_sha, lock_meta
    )
    bot.cas_update_lock_ref = lambda new_sha: lease_lock.cas_update_lock_ref(bot, new_sha)
    bot.lock_is_currently_valid = lambda lock_meta, now=None: lease_lock.lock_is_currently_valid(
        bot, lock_meta, now
    )
    return bot


def test_acquire_lock_retries_until_expected_token_visible():
    bot = _lease_bot()
    snapshots = iter(
        [
            ("old-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("stale-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("stale-ref-2", "tree", {"lock_state": "unlocked", "lock_token": None}),
            (
                "new-ref",
                "tree",
                {
                    "lock_state": "locked",
                    "lock_token": "token-123",
                    "lock_owner_run_id": "local-run",
                    "lock_owner_workflow": "reviewer-bot",
                    "lock_owner_job": "reviewer-bot",
                    "lock_expires_at": "2999-01-01T00:00:00+00:00",
                },
            ),
        ]
    )

    bot.get_lock_ref_snapshot = lambda: next(snapshots)
    bot.create_lock_commit = lambda parent_sha, tree_sha, lock_meta: GitHubApiResult(
        201, {"sha": "commit-1"}, {}, "", True
    )
    bot.cas_update_lock_ref = lambda new_sha: GitHubApiResult(200, {}, {}, "", True)

    context = lease_lock.acquire_state_issue_lease_lock(bot)

    assert context.lock_token == "token-123"
    assert bot.ACTIVE_LEASE_CONTEXT is context


def test_acquire_lock_fails_closed_on_conflicting_visible_token(monkeypatch):
    bot = _lease_bot()
    snapshots = iter(
        [
            ("old-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("new-ref", "tree", {"lock_state": "locked", "lock_token": "other-token"}),
        ]
    )

    bot.get_lock_ref_snapshot = lambda: next(snapshots)
    bot.create_lock_commit = lambda parent_sha, tree_sha, lock_meta: GitHubApiResult(
        201, {"sha": "commit-1"}, {}, "", True
    )
    bot.cas_update_lock_ref = lambda new_sha: GitHubApiResult(200, {}, {}, "", True)

    with pytest.raises(RuntimeError, match="unexpected lock state"):
        lease_lock.acquire_state_issue_lease_lock(bot)


def test_acquire_lock_succeeds_when_later_loop_observes_own_valid_token():
    bot = _lease_bot()
    snapshots = iter(
        [
            ("old-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("stale-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            (
                "new-ref",
                "tree",
                {
                    "lock_state": "locked",
                    "lock_token": "token-123",
                    "lock_owner_run_id": "local-run",
                    "lock_owner_workflow": "reviewer-bot",
                    "lock_owner_job": "reviewer-bot",
                    "lock_expires_at": "2999-01-01T00:00:00+00:00",
                },
            ),
        ]
    )

    bot.get_lock_ref_snapshot = lambda: next(snapshots)
    bot.create_lock_commit = lambda parent_sha, tree_sha, lock_meta: GitHubApiResult(
        201, {"sha": "commit-1"}, {}, "", True
    )
    bot.cas_update_lock_ref = lambda new_sha: GitHubApiResult(200, {}, {}, "", True)

    context = lease_lock.acquire_state_issue_lease_lock(bot)

    assert context.lock_token == "token-123"
    assert bot.ACTIVE_LEASE_CONTEXT is context


def test_acquire_lock_fails_closed_when_own_token_has_mismatched_owner():
    bot = _lease_bot()
    snapshots = iter(
        [
            (
                "new-ref",
                "tree",
                {
                    "lock_state": "locked",
                    "lock_token": "token-123",
                    "lock_owner_run_id": "someone-else",
                    "lock_owner_workflow": "reviewer-bot",
                    "lock_owner_job": "reviewer-bot",
                    "lock_expires_at": "2999-01-01T00:00:00+00:00",
                },
            )
        ]
    )

    bot.get_lock_ref_snapshot = lambda: next(snapshots)

    with pytest.raises(RuntimeError, match="owner metadata drifted"):
        lease_lock.acquire_state_issue_lease_lock(bot)


def test_release_lock_retries_stale_unlocked_predecessor(monkeypatch):
    context = LeaseContext(
        lock_token="token-123",
        lock_owner_run_id="run",
        lock_owner_workflow="workflow",
        lock_owner_job="job",
        state_issue_url="https://example.com/issues/314",
        lock_ref="refs/heads/reviewer-bot-state-lock",
        lock_expires_at="2999-01-01T00:00:00+00:00",
    )
    bot = _lease_bot(ACTIVE_LEASE_CONTEXT=context)
    snapshots = iter(
        [
            ("stale-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("new-ref", "tree", {"lock_state": "locked", "lock_token": "token-123"}),
        ]
    )

    bot.get_lock_ref_snapshot = lambda: next(snapshots)
    bot.create_lock_commit = lambda parent_sha, tree_sha, lock_meta: GitHubApiResult(
        201, {"sha": "commit-2"}, {}, "", True
    )
    bot.cas_update_lock_ref = lambda new_sha: GitHubApiResult(200, {}, {}, "", True)

    assert lease_lock.release_state_issue_lease_lock(bot) is True
    assert bot.ACTIVE_LEASE_CONTEXT is None


def test_release_lock_fails_closed_on_conflicting_token(monkeypatch):
    context = LeaseContext(
        lock_token="token-123",
        lock_owner_run_id="run",
        lock_owner_workflow="workflow",
        lock_owner_job="job",
        state_issue_url="https://example.com/issues/314",
        lock_ref="refs/heads/reviewer-bot-state-lock",
        lock_expires_at="2999-01-01T00:00:00+00:00",
    )
    bot = _lease_bot(ACTIVE_LEASE_CONTEXT=context)
    bot.get_lock_ref_snapshot = lambda: (
        "new-ref",
        "tree",
        {"lock_state": "locked", "lock_token": "other-token"},
    )

    assert lease_lock.release_state_issue_lease_lock(bot) is False
    assert bot.ACTIVE_LEASE_CONTEXT is None


def test_ensure_lock_ref_exists_uses_retry_aware_reads(monkeypatch):
    observed = []

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed.append((endpoint, kwargs.get("retry_policy")))
        if endpoint == "git/ref/heads/reviewer-bot-state-lock" and len(observed) == 1:
            return GitHubApiResult(
                status_code=404,
                payload={"message": "missing"},
                headers={},
                text="missing",
                ok=False,
                failure_kind="not_found",
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "git/ref/heads/reviewer-bot-state-lock":
            return GitHubApiResult(
                status_code=200,
                payload={"object": {"sha": "base-sha"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "git/ref/heads/main":
            return GitHubApiResult(
                status_code=200,
                payload={"object": {"sha": "base-sha"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=1,
                transport_error=None,
            )
        if endpoint == "git/refs":
            return GitHubApiResult(
                status_code=201,
                payload={"ref": "refs/heads/reviewer-bot-state-lock"},
                headers={},
                text="created",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    bot = _lease_bot(github_api_request=fake_request)

    assert lease_lock.ensure_lock_ref_exists(bot) == "base-sha"
    assert observed[0] == ("git/ref/heads/reviewer-bot-state-lock", "idempotent_read")
    assert observed[1] == ("git/ref/heads/main", "idempotent_read")


def test_ensure_lock_ref_exists_fails_closed_when_bootstrap_branch_unavailable(monkeypatch):
    responses = iter(
        [
            GitHubApiResult(404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None),
            GitHubApiResult(502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None),
        ]
    )
    bot = _lease_bot(github_api_request=lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="Unable to read bootstrap branch"):
        lease_lock.ensure_lock_ref_exists(bot)


def test_get_lock_ref_snapshot_fails_closed_on_invalid_commit_payload():
    responses = iter(
        [
            GitHubApiResult(
                status_code=200,
                payload={"object": {"sha": "ref-sha"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            ),
            GitHubApiResult(
                status_code=200,
                payload={"message": "missing tree"},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            ),
        ]
    )
    bot = _lease_bot(github_api_request=lambda method, endpoint, data=None, extra_headers=None, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="missing tree SHA"):
        lease_lock.get_lock_ref_snapshot(bot)


def test_renew_state_issue_lease_lock_fails_on_token_mismatch(monkeypatch):
    context = LeaseContext(
        lock_token="expected-token",
        lock_owner_run_id="run-1",
        lock_owner_workflow="wf",
        lock_owner_job="job",
        state_issue_url="https://example.com/state/1",
    )
    bot = _lease_bot()
    bot.get_lock_ref_snapshot = lambda: (
        "ref-sha",
        "tree-sha",
        {"lock_token": "different-token", "lock_state": "locked"},
    )

    assert lease_lock.renew_state_issue_lease_lock(bot, context) is False


def test_ensure_lock_ref_exists_fails_closed_when_lock_ref_read_remains_unavailable(monkeypatch):
    bot = _lease_bot(
        github_api_request=lambda *args, **kwargs: GitHubApiResult(
            502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
        )
    )

    with pytest.raises(RuntimeError, match="Failed to read reviewer-bot lock ref"):
        lease_lock.ensure_lock_ref_exists(bot)


def test_ensure_lock_ref_exists_fails_closed_when_bootstrap_branch_sha_missing(monkeypatch):
    responses = iter(
        [
            GitHubApiResult(404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None),
            GitHubApiResult(200, {"object": {}}, {}, "ok", True, None, 0, None),
        ]
    )
    bot = _lease_bot(github_api_request=lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="Bootstrap branch ref did not include SHA"):
        lease_lock.ensure_lock_ref_exists(bot)


def test_get_lock_ref_snapshot_fails_closed_when_commit_fetch_unavailable():
    responses = iter(
        [
            GitHubApiResult(
                status_code=200,
                payload={"object": {"sha": "ref-sha"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            ),
            GitHubApiResult(502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None),
        ]
    )
    bot = _lease_bot(github_api_request=lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="Failed to read lock commit"):
        lease_lock.get_lock_ref_snapshot(bot)
