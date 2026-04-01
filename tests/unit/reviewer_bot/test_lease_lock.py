import pytest

from scripts import reviewer_bot


def test_acquire_lock_retries_until_expected_token_visible(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot.lease_lock_module,
        "get_lock_owner_context",
        lambda: ("local-run", "reviewer-bot", "reviewer-bot"),
    )
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

    monkeypatch.setattr(
        reviewer_bot.lease_lock_module.uuid, "uuid4", lambda: type("U", (), {"hex": "token-123"})()
    )
    monkeypatch.setattr(reviewer_bot.lease_lock_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(reviewer_bot, "get_lock_ref_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            201, {"sha": "commit-1"}, {}, "", True
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(200, {}, {}, "", True),
    )
    monkeypatch.setattr(reviewer_bot, "get_state_issue_html_url", lambda: "https://example.com/issues/314")
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)

    context = reviewer_bot.acquire_state_issue_lease_lock()

    assert context.lock_token == "token-123"
    assert reviewer_bot.ACTIVE_LEASE_CONTEXT is context


def test_acquire_lock_fails_closed_on_conflicting_visible_token(monkeypatch):
    snapshots = iter(
        [
            ("old-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("new-ref", "tree", {"lock_state": "locked", "lock_token": "other-token"}),
        ]
    )

    monkeypatch.setattr(
        reviewer_bot.lease_lock_module.uuid, "uuid4", lambda: type("U", (), {"hex": "token-123"})()
    )
    monkeypatch.setattr(reviewer_bot.lease_lock_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(reviewer_bot, "get_lock_ref_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            201, {"sha": "commit-1"}, {}, "", True
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(200, {}, {}, "", True),
    )
    monkeypatch.setattr(reviewer_bot, "get_state_issue_html_url", lambda: "https://example.com/issues/314")
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)

    with pytest.raises(RuntimeError, match="unexpected lock state"):
        reviewer_bot.acquire_state_issue_lease_lock()


def test_acquire_lock_succeeds_when_later_loop_observes_own_valid_token(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot.lease_lock_module,
        "get_lock_owner_context",
        lambda: ("local-run", "reviewer-bot", "reviewer-bot"),
    )
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

    monkeypatch.setattr(
        reviewer_bot.lease_lock_module.uuid, "uuid4", lambda: type("U", (), {"hex": "token-123"})()
    )
    monkeypatch.setattr(reviewer_bot.lease_lock_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(reviewer_bot, "get_lock_ref_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            201, {"sha": "commit-1"}, {}, "", True
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(200, {}, {}, "", True),
    )
    monkeypatch.setattr(reviewer_bot, "get_state_issue_html_url", lambda: "https://example.com/issues/314")
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)

    context = reviewer_bot.acquire_state_issue_lease_lock()

    assert context.lock_token == "token-123"
    assert reviewer_bot.ACTIVE_LEASE_CONTEXT is context


def test_acquire_lock_fails_closed_when_own_token_has_mismatched_owner(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot.lease_lock_module,
        "get_lock_owner_context",
        lambda: ("local-run", "reviewer-bot", "reviewer-bot"),
    )
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

    monkeypatch.setattr(
        reviewer_bot.lease_lock_module.uuid, "uuid4", lambda: type("U", (), {"hex": "token-123"})()
    )
    monkeypatch.setattr(reviewer_bot.lease_lock_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(reviewer_bot, "get_lock_ref_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(reviewer_bot, "get_state_issue_html_url", lambda: "https://example.com/issues/314")
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)

    with pytest.raises(RuntimeError, match="owner metadata drifted"):
        reviewer_bot.acquire_state_issue_lease_lock()


def test_release_lock_retries_stale_unlocked_predecessor(monkeypatch):
    context = reviewer_bot.LeaseContext(
        lock_token="token-123",
        lock_owner_run_id="run",
        lock_owner_workflow="workflow",
        lock_owner_job="job",
        state_issue_url="https://example.com/issues/314",
        lock_ref="refs/heads/reviewer-bot-state-lock",
        lock_expires_at="2999-01-01T00:00:00+00:00",
    )
    snapshots = iter(
        [
            ("stale-ref", "tree", {"lock_state": "unlocked", "lock_token": None}),
            ("new-ref", "tree", {"lock_state": "locked", "lock_token": "token-123"}),
        ]
    )

    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", context)
    monkeypatch.setattr(reviewer_bot.lease_lock_module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(reviewer_bot, "get_lock_ref_snapshot", lambda: next(snapshots))
    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            201, {"sha": "commit-2"}, {}, "", True
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(200, {}, {}, "", True),
    )

    assert reviewer_bot.release_state_issue_lease_lock() is True
    assert reviewer_bot.ACTIVE_LEASE_CONTEXT is None


def test_release_lock_fails_closed_on_conflicting_token(monkeypatch):
    context = reviewer_bot.LeaseContext(
        lock_token="token-123",
        lock_owner_run_id="run",
        lock_owner_workflow="workflow",
        lock_owner_job="job",
        state_issue_url="https://example.com/issues/314",
        lock_ref="refs/heads/reviewer-bot-state-lock",
        lock_expires_at="2999-01-01T00:00:00+00:00",
    )
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", context)
    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("new-ref", "tree", {"lock_state": "locked", "lock_token": "other-token"}),
    )

    assert reviewer_bot.release_state_issue_lease_lock() is False
    assert reviewer_bot.ACTIVE_LEASE_CONTEXT is None


def test_ensure_lock_ref_exists_uses_retry_aware_reads(monkeypatch):
    observed = []

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed.append((endpoint, kwargs.get("retry_policy")))
        if endpoint == "git/ref/heads/reviewer-bot-state-lock" and len(observed) == 1:
            return reviewer_bot.GitHubApiResult(
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
            return reviewer_bot.GitHubApiResult(
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
            return reviewer_bot.GitHubApiResult(
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
            return reviewer_bot.GitHubApiResult(
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

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_NAME", "heads/reviewer-bot-state-lock")
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_BOOTSTRAP_BRANCH", "main")

    assert reviewer_bot.ensure_lock_ref_exists() == "base-sha"
    assert observed[0] == ("git/ref/heads/reviewer-bot-state-lock", "idempotent_read")
    assert observed[1] == ("git/ref/heads/main", "idempotent_read")


def test_ensure_lock_ref_exists_fails_closed_when_bootstrap_branch_unavailable(monkeypatch):
    responses = iter(
        [
            reviewer_bot.GitHubApiResult(
                404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None
            ),
            reviewer_bot.GitHubApiResult(
                502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
            ),
        ]
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_NAME", "heads/reviewer-bot-state-lock")
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_BOOTSTRAP_BRANCH", "main")

    with pytest.raises(RuntimeError, match="Unable to read bootstrap branch"):
        reviewer_bot.ensure_lock_ref_exists()


def test_get_lock_ref_snapshot_fails_closed_on_invalid_commit_payload(monkeypatch):
    monkeypatch.setattr(reviewer_bot.lease_lock_module, "ensure_lock_ref_exists", lambda bot: "ref-sha")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"message": "missing tree"},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="missing tree SHA"):
        reviewer_bot.get_lock_ref_snapshot()


def test_renew_state_issue_lease_lock_fails_on_token_mismatch(monkeypatch):
    context = reviewer_bot.LeaseContext(
        lock_token="expected-token",
        lock_owner_run_id="run-1",
        lock_owner_workflow="wf",
        lock_owner_job="job",
        state_issue_url="https://example.com/state/1",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("ref-sha", "tree-sha", {"lock_token": "different-token", "lock_state": "locked"}),
    )

    assert reviewer_bot.renew_state_issue_lease_lock(context) is False


def test_ensure_lock_ref_exists_fails_closed_when_lock_ref_read_remains_unavailable(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: reviewer_bot.GitHubApiResult(
            502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to read reviewer-bot lock ref"):
        reviewer_bot.ensure_lock_ref_exists()


def test_ensure_lock_ref_exists_fails_closed_when_bootstrap_branch_sha_missing(monkeypatch):
    responses = iter(
        [
            reviewer_bot.GitHubApiResult(
                404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None
            ),
            reviewer_bot.GitHubApiResult(200, {"object": {}}, {}, "ok", True, None, 0, None),
        ]
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="Bootstrap branch ref did not include SHA"):
        reviewer_bot.ensure_lock_ref_exists()


def test_get_lock_ref_snapshot_fails_closed_when_commit_fetch_unavailable(monkeypatch):
    monkeypatch.setattr(reviewer_bot.lease_lock_module, "ensure_lock_ref_exists", lambda bot: "ref-sha")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: reviewer_bot.GitHubApiResult(
            502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to read lock commit"):
        reviewer_bot.get_lock_ref_snapshot()
