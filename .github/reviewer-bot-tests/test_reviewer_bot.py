import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REVIEWER_BOT_PATH = REPO_ROOT / "scripts" / "reviewer_bot.py"


spec = importlib.util.spec_from_file_location("reviewer_bot", REVIEWER_BOT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("Unable to load reviewer_bot module")
reviewer_bot = importlib.util.module_from_spec(spec)
sys.modules["reviewer_bot"] = reviewer_bot
spec.loader.exec_module(reviewer_bot)


def make_state():
    return {
        "last_updated": None,
        "current_index": 0,
        "queue": [
            {"github": "alice", "name": "Alice"},
            {"github": "bob", "name": "Bob"},
            {"github": "carol", "name": "Carol"},
        ],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},
    }


@pytest.fixture(autouse=True)
def clear_env():
    env_vars = {
        "COMMENT_BODY",
        "COMMENT_AUTHOR",
        "COMMENT_ID",
        "EVENT_ACTION",
        "EVENT_NAME",
        "ISSUE_NUMBER",
        "ISSUE_AUTHOR",
        "IS_PULL_REQUEST",
        "PR_IS_CROSS_REPOSITORY",
        "REVIEW_AUTHOR",
        "REVIEW_STATE",
        "REPO_OWNER",
        "REPO_NAME",
        "WORKFLOW_RUN_EVENT",
        "WORKFLOW_RUN_HEAD_SHA",
        "WORKFLOW_RUN_RECONCILE_PR_NUMBER",
        "WORKFLOW_RUN_RECONCILE_HEAD_SHA",
        "WORKFLOW_RUN_ID",
        "WORKFLOW_NAME",
        "WORKFLOW_JOB_NAME",
    }
    with pytest.MonkeyPatch().context() as monkeypatch:
        for name in env_vars:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(
            reviewer_bot,
            "ACTIVE_LEASE_CONTEXT",
            reviewer_bot.LeaseContext(
                lock_token="test-lock-token",
                lock_owner_run_id="test-run",
                lock_owner_workflow="test-workflow",
                lock_owner_job="test-job",
                state_issue_url="https://example.com/state",
            ),
        )
        yield


@pytest.fixture
def stub_api(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={},
            headers={},
            text="",
            ok=True,
        ),
    )
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "assign_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        reviewer_bot,
        "request_reviewer_assignment",
        lambda *args, **kwargs: reviewer_bot.AssignmentAttempt(success=True, status_code=201),
    )
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_pr_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_assignee", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda *args, **kwargs: {"a", "b"})
    monkeypatch.setattr(reviewer_bot, "add_label", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "add_label_with_status", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_label", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_label_with_status", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "ensure_label_exists", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "fetch_members", lambda *args, **kwargs: [])


@pytest.fixture
def captured_comments(monkeypatch):
    comments = []

    def record_comment(issue_number, body):
        comments.append({"issue_number": issue_number, "body": body})
        return True

    monkeypatch.setattr(reviewer_bot, "post_comment", record_comment)
    return comments


def test_parse_state_from_issue_yaml_block():
    issue = {
        "body": """## State\n\n```yaml\nqueue:\n  - github: alice\n    name: Alice\ncurrent_index: 1\n```
"""
    }
    state = reviewer_bot.parse_state_from_issue(issue)
    assert state["queue"][0]["github"] == "alice"
    assert state["current_index"] == 1


def test_parse_state_from_issue_raw_yaml():
    issue = {"body": "queue:\n  - github: bob\n    name: Bob\ncurrent_index: 2\n"}
    state = reviewer_bot.parse_state_from_issue(issue)
    assert state["queue"][0]["github"] == "bob"
    assert state["current_index"] == 2


def test_parse_state_invalid_yaml_returns_empty():
    issue = {"body": "queue: ["}
    state = reviewer_bot.parse_state_from_issue(issue)
    assert state == {}


def test_load_state_applies_defaults(monkeypatch):
    issue = {"body": "current_index: 3\nqueue: null\npass_until: null\nrecent_assignments: null\nactive_reviews: null\n"}
    monkeypatch.setattr(reviewer_bot, "get_state_issue", lambda: issue)
    state = reviewer_bot.load_state()
    assert state["current_index"] == 3
    assert state["queue"] == []
    assert state["pass_until"] == []
    assert state["recent_assignments"] == []
    assert state["active_reviews"] == {}


def test_save_state_formats_issue_body(monkeypatch):
    payload = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 314)

    initial_body = reviewer_bot.render_state_issue_body(make_state(), reviewer_bot.clear_lock_metadata())

    monkeypatch.setattr(
        reviewer_bot,
        "get_state_issue_snapshot",
        lambda: reviewer_bot.StateIssueSnapshot(
            body=initial_body,
            etag='"abc123"',
            html_url="https://example.com/issues/314",
        ),
    )

    def capture_patch(body, etag):
        payload["body"] = body
        payload["etag"] = etag
        return reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"ok": True},
            headers={},
            text="",
            ok=True,
        )

    monkeypatch.setattr(reviewer_bot, "conditional_patch_state_issue", capture_patch)
    state = make_state()
    assert reviewer_bot.save_state(state) is True
    assert payload["etag"] == '"abc123"'
    assert reviewer_bot.STATE_BLOCK_START_MARKER in payload["body"]
    assert reviewer_bot.LOCK_BLOCK_START_MARKER in payload["body"]
    assert "```yaml" in payload["body"]


def test_parse_lock_metadata_from_issue_body_uses_markers():
    lock_meta = reviewer_bot.normalize_lock_metadata(
        {
            "schema_version": 1,
            "lock_owner_run_id": "123",
            "lock_owner_workflow": "Reviewer Bot",
            "lock_owner_job": "reviewer-bot",
            "lock_token": "abcdef",
            "lock_acquired_at": "2026-02-11T00:00:00+00:00",
            "lock_expires_at": "2026-02-11T00:05:00+00:00",
        }
    )
    body = reviewer_bot.render_state_issue_body(make_state(), lock_meta)

    parsed = reviewer_bot.parse_lock_metadata_from_issue_body(body)

    assert parsed == lock_meta


def test_save_state_preserves_lock_metadata_across_save(monkeypatch):
    payload = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 314)
    expected_lock_meta = reviewer_bot.normalize_lock_metadata(
        {
            "schema_version": 1,
            "lock_owner_run_id": "run-42",
            "lock_owner_workflow": "Reviewer Bot",
            "lock_owner_job": "reviewer-bot",
            "lock_token": "lock-token-42",
            "lock_acquired_at": "2026-02-11T10:00:00+00:00",
            "lock_expires_at": "2026-02-11T10:05:00+00:00",
        }
    )
    initial_body = reviewer_bot.render_state_issue_body(make_state(), expected_lock_meta)

    monkeypatch.setattr(
        reviewer_bot,
        "get_state_issue_snapshot",
        lambda: reviewer_bot.StateIssueSnapshot(
            body=initial_body,
            etag='"etag-state"',
            html_url="https://example.com/issues/314",
        ),
    )

    def capture_patch(body, etag):
        payload["body"] = body
        payload["etag"] = etag
        return reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"ok": True},
            headers={},
            text="",
            ok=True,
        )

    monkeypatch.setattr(reviewer_bot, "conditional_patch_state_issue", capture_patch)

    state = make_state()
    assert reviewer_bot.save_state(state) is True
    assert payload["etag"] == '"etag-state"'
    parsed_lock = reviewer_bot.parse_lock_metadata_from_issue_body(payload["body"])
    assert parsed_lock == expected_lock_meta


def test_strip_code_blocks_removes_fenced_indented_inline():
    body = """
Here is a command:
```
@guidelines-bot /pass
```
    @guidelines-bot /queue
And `@guidelines-bot /commands` inline.
"""
    sanitized = reviewer_bot.strip_code_blocks(body)
    assert "/pass" not in sanitized
    assert "/queue" not in sanitized
    assert "/commands" not in sanitized


def test_parse_command_single_command():
    command, args = reviewer_bot.parse_command("@guidelines-bot /queue")
    assert command == "queue"
    assert args == []


def test_parse_command_pass_reason():
    command, args = reviewer_bot.parse_command("@guidelines-bot /pass reason here")
    assert command == "pass"
    assert args == ["reason", "here"]


def test_parse_command_rectify():
    command, args = reviewer_bot.parse_command("@guidelines-bot /rectify")
    assert command == "rectify"
    assert args == []


def test_parse_command_multiple_commands():
    command, args = reviewer_bot.parse_command(
        "@guidelines-bot /queue\n@guidelines-bot /commands"
    )
    assert command == "_multiple_commands"
    assert args == []


def test_parse_command_malformed_known():
    command, args = reviewer_bot.parse_command("@guidelines-bot pass")
    assert command == "_malformed_known"
    assert args == ["pass"]


def test_parse_command_malformed_unknown():
    command, args = reviewer_bot.parse_command("@guidelines-bot greetings")
    assert command == "_malformed_unknown"
    assert args == ["greetings"]


@pytest.mark.parametrize(
    ("guidance_builder", "builder_args"),
    [
        (reviewer_bot.get_issue_guidance, ("alice", "bob")),
        (reviewer_bot.get_fls_audit_guidance, ("alice", "bob")),
        (reviewer_bot.get_pr_guidance, ("alice", "bob")),
    ],
)
def test_guidance_release_commands_are_explicit(guidance_builder, builder_args):
    guidance = guidance_builder(*builder_args)
    assert "@guidelines-bot /release [reason]" in guidance
    assert "@guidelines-bot /release @username [reason]" in guidance


def test_github_api_error_handling(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self.content = content
            self.text = "error"
            self.headers = {}

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(reviewer_bot, "get_github_token", lambda: "token")
    monkeypatch.setenv("REPO_OWNER", "owner")
    monkeypatch.setenv("REPO_NAME", "repo")

    def fake_request(*args, **kwargs):
        return FakeResponse(500, b"error")

    monkeypatch.setattr(reviewer_bot.requests, "request", fake_request)
    assert reviewer_bot.github_api("GET", "issues/1") is None


def test_acquire_state_issue_lease_lock_success(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)
    monkeypatch.setenv("WORKFLOW_RUN_ID", "9001")
    monkeypatch.setenv("WORKFLOW_NAME", "Reviewer Bot")
    monkeypatch.setenv("WORKFLOW_JOB_NAME", "reviewer-bot")
    monkeypatch.setattr(reviewer_bot.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(reviewer_bot.time, "sleep", lambda _: None)
    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("parent-sha", "tree-sha", reviewer_bot.clear_lock_metadata()),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            status_code=201,
            payload={"sha": "new-lock-commit-sha"},
            headers={},
            text="",
            ok=True,
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"ok": True},
            headers={},
            text="",
            ok=True,
        ),
    )

    ctx = reviewer_bot.acquire_state_issue_lease_lock()

    assert ctx.lock_owner_run_id == "9001"
    assert ctx.lock_owner_workflow == "Reviewer Bot"
    assert ctx.lock_owner_job == "reviewer-bot"
    assert reviewer_bot.ACTIVE_LEASE_CONTEXT is not None
    assert ctx.lock_ref == "refs/heads/reviewer-bot-state-lock"
    assert isinstance(ctx.lock_expires_at, str)


def test_acquire_state_issue_lease_lock_retries_on_conflict(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)
    monkeypatch.setattr(reviewer_bot.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(reviewer_bot.time, "sleep", lambda _: None)

    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("parent-sha", "tree-sha", reviewer_bot.clear_lock_metadata()),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            status_code=201,
            payload={"sha": "new-lock-commit-sha"},
            headers={},
            text="",
            ok=True,
        ),
    )
    statuses = iter([409, 200])
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(
            status_code=next(statuses),
            payload={"ok": True},
            headers={},
            text="",
            ok=True,
        ),
    )

    ctx = reviewer_bot.acquire_state_issue_lease_lock()
    assert ctx.lock_token


def test_acquire_state_issue_lease_lock_takes_over_expired_lock(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)
    monkeypatch.setattr(reviewer_bot.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(reviewer_bot.time, "sleep", lambda _: None)

    expired_lock = reviewer_bot.normalize_lock_metadata(
        {
            "schema_version": 1,
            "lock_owner_run_id": "123",
            "lock_owner_workflow": "Reviewer Bot",
            "lock_owner_job": "reviewer-bot",
            "lock_state": "locked",
            "lock_token": "stale-lock",
            "lock_acquired_at": "2020-01-01T00:00:00+00:00",
            "lock_expires_at": "2020-01-01T00:01:00+00:00",
        }
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("parent-sha", "tree-sha", expired_lock),
    )

    monkeypatch.setattr(
        reviewer_bot,
        "create_lock_commit",
        lambda parent_sha, tree_sha, lock_meta: reviewer_bot.GitHubApiResult(
            status_code=201,
            payload={"sha": "new-lock-commit-sha"},
            headers={},
            text="",
            ok=True,
        ),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "cas_update_lock_ref",
        lambda new_sha: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"ok": True},
            headers={},
            text="",
            ok=True,
        ),
    )

    ctx = reviewer_bot.acquire_state_issue_lease_lock()
    assert ctx.lock_token != "stale-lock"


def test_acquire_state_issue_lease_lock_times_out(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", None)
    monkeypatch.setattr(reviewer_bot, "LOCK_MAX_WAIT_SECONDS", 1)
    monkeypatch.setattr(reviewer_bot.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(reviewer_bot.time, "sleep", lambda _: None)

    valid_lock = reviewer_bot.normalize_lock_metadata(
        {
            "schema_version": 1,
            "lock_owner_run_id": "other-run",
            "lock_owner_workflow": "Reviewer Bot",
            "lock_owner_job": "reviewer-bot",
            "lock_state": "locked",
            "lock_token": "active-lock",
            "lock_acquired_at": "2999-01-01T00:00:00+00:00",
            "lock_expires_at": "2999-01-01T00:10:00+00:00",
        }
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("parent-sha", "tree-sha", valid_lock),
    )

    monotonic_values = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(reviewer_bot.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(RuntimeError, match="Timed out waiting for reviewer-bot lease lock"):
        reviewer_bot.acquire_state_issue_lease_lock()


def test_handle_pass_command_requires_current_reviewer(stub_api, monkeypatch):
    state = make_state()
    issue_number = 123
    state["active_reviews"][str(issue_number)] = {
        "skipped": [],
        "current_reviewer": "alice",
    }
    response, success = reviewer_bot.handle_pass_command(
        state, issue_number, "bob", None
    )
    assert success is False
    assert "Only the currently assigned reviewer" in response
    assert state["active_reviews"][str(issue_number)]["skipped"] == []


def test_handle_pass_command_allows_current_reviewer(stub_api, monkeypatch):
    state = make_state()
    issue_number = 123
    state["active_reviews"][str(issue_number)] = {
        "skipped": [],
        "current_reviewer": "alice",
    }
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "bob")
    response, success = reviewer_bot.handle_pass_command(
        state, issue_number, "alice", None
    )
    assert success is True
    assert "has passed" in response
    assert "bob" in response
    assert "alice" in state["active_reviews"][str(issue_number)]["skipped"]


def test_reposition_member_as_next_moves_user():
    state = make_state()
    state["current_index"] = 2
    assert reviewer_bot.reposition_member_as_next(state, "alice") is True
    assert state["queue"][state["current_index"]]["github"] == "alice"


def test_reposition_member_as_next_missing_user():
    state = make_state()
    assert reviewer_bot.reposition_member_as_next(state, "zoe") is False


def test_get_next_reviewer_skips_and_advances():
    state = make_state()
    state["current_index"] = 0
    reviewer = reviewer_bot.get_next_reviewer(state, skip_usernames={"alice"})
    assert reviewer == "bob"
    assert state["current_index"] == 2


def test_record_assignment_caps_list(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "MAX_RECENT_ASSIGNMENTS", 2)
    reviewer_bot.record_assignment(state, "alice", 1, "issue")
    reviewer_bot.record_assignment(state, "bob", 2, "issue")
    reviewer_bot.record_assignment(state, "carol", 3, "issue")
    assert len(state["recent_assignments"]) == 2
    assert state["recent_assignments"][0]["github"] == "carol"


def test_handle_comment_event_ignores_multiple_commands(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /queue\n@guidelines-bot /commands"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    reviewer_bot.handle_comment_event(state)
    assert len(captured_comments) == 1
    assert "Multiple bot commands" in captured_comments[0]["body"]
    assert "/commands" in captured_comments[0]["body"]


def test_handle_comment_event_ignores_commands_in_code_block(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
        "last_reviewer_activity": None,
        "assigned_at": None,
    }
    os.environ["COMMENT_BODY"] = """
Example:
```
@guidelines-bot /queue
```
"""
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert captured_comments == []


def test_handle_comment_event_pass_command(stub_api, captured_comments, monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
    }
    os.environ["COMMENT_BODY"] = "@guidelines-bot /pass" 
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "bob")
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "has passed" in captured_comments[0]["body"]


def test_handle_comment_event_rectify_command(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /rectify"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"

    observed = {}

    def fake_handle_rectify(passed_state, issue_number, comment_author):
        observed["state"] = passed_state
        observed["issue_number"] = issue_number
        observed["comment_author"] = comment_author
        return "rectified", True, True

    monkeypatch.setattr(reviewer_bot, "handle_rectify_command", fake_handle_rectify)

    handled = reviewer_bot.handle_comment_event(state)

    assert handled is True
    assert observed["state"] is state
    assert observed["issue_number"] == 42
    assert observed["comment_author"] == "alice"
    assert len(captured_comments) == 1
    assert captured_comments[0]["body"] == "rectified"


def test_handle_comment_event_claim_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /claim"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "has claimed" in captured_comments[0]["body"]


def test_handle_comment_event_label_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /label +a -b"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "Added label" in captured_comments[0]["body"]


def test_handle_comment_event_label_command_with_hyphen(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /label +sign-off: create pr -sign-off: create pr"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    monkeypatch.setattr(
        reviewer_bot,
        "get_repo_labels",
        lambda *args, **kwargs: {"sign-off: create pr"},
    )
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "Added label `sign-off: create pr`" in captured_comments[0]["body"]
    assert "Removed label `sign-off: create pr`" in captured_comments[0]["body"]


def test_handle_comment_event_accept_no_fls_changes(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /accept-no-fls-changes"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    monkeypatch.setattr(
        reviewer_bot,
        "handle_accept_no_fls_changes_command",
        lambda *args, **kwargs: ("ok", True),
    )
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert captured_comments[0]["body"] == "ok"


def test_handle_comment_event_queue_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /queue"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "Queue Status" in captured_comments[0]["body"]


def test_handle_comment_event_commands_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /commands"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    response = captured_comments[0]["body"]
    assert "Available Commands" in response
    assert "@guidelines-bot /release [reason]" in response
    assert "@guidelines-bot /release @username [reason]" in response


def test_handle_comment_event_away_command(stub_api, captured_comments, monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
    }
    os.environ["COMMENT_BODY"] = "@guidelines-bot /away 2099-01-01"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "bob")
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "now away until" in captured_comments[0]["body"]


def test_handle_comment_event_release_command_self(stub_api, captured_comments, monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
        "assignment_method": "round-robin",
    }
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: ["alice"])
    os.environ["COMMENT_BODY"] = "@guidelines-bot /release"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "has released" in captured_comments[0]["body"]


def test_handle_comment_event_release_command_self_not_current_suggests_target(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
        "assignment_method": "round-robin",
    }
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: ["alice"])
    os.environ["COMMENT_BODY"] = "@guidelines-bot /release"
    os.environ["COMMENT_AUTHOR"] = "bob"
    os.environ["ISSUE_NUMBER"] = "42"

    handled = reviewer_bot.handle_comment_event(state)

    assert handled is False
    assert len(captured_comments) == 1
    response = captured_comments[0]["body"]
    assert "@bob is not the current reviewer" in response
    assert "Current reviewer: @alice" in response
    assert "@guidelines-bot /release @alice" in response
    assert "triage+ required" in response


def test_handle_release_command_self_not_assigned_uses_single_assignee_hint(stub_api, monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: ["alice"])

    response, success = reviewer_bot.handle_release_command(
        state=state,
        issue_number=42,
        comment_author="bob",
        args=[],
    )

    assert success is False
    assert "@bob is not assigned to this issue/PR" in response
    assert "Current assignee(s): @alice" in response
    assert "@guidelines-bot /release @alice" in response
    assert "triage+ required" in response


def test_handle_comment_event_release_command_other_requires_permission(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
        "assignment_method": "round-robin",
    }
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: ["alice"])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: False)
    os.environ["COMMENT_BODY"] = "@guidelines-bot /release @alice"
    os.environ["COMMENT_AUTHOR"] = "bob"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "does not have permission" in captured_comments[0]["body"]


def test_handle_release_command_other_with_permission(stub_api, captured_comments, monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "skipped": [],
        "current_reviewer": "alice",
        "assignment_method": "round-robin",
    }
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: ["alice"])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: True)
    os.environ["COMMENT_BODY"] = "@guidelines-bot /release @alice"
    os.environ["COMMENT_AUTHOR"] = "bob"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "has released @alice" in captured_comments[0]["body"]


def test_handle_comment_event_assign_user(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /r? @bob"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "has been assigned" in captured_comments[0]["body"]


def test_handle_comment_event_assign_from_queue(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /r? producers"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "bob")
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is True
    assert len(captured_comments) == 2
    assert "assigned as reviewer" in captured_comments[1]["body"]


def test_handle_assign_from_queue_truthful_when_pr_request_returns_422(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    os.environ["IS_PULL_REQUEST"] = "true"
    os.environ["ISSUE_AUTHOR"] = "dana"

    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(
        reviewer_bot,
        "request_reviewer_assignment",
        lambda *args, **kwargs: reviewer_bot.AssignmentAttempt(success=False, status_code=422),
    )

    response, success = reviewer_bot.handle_assign_from_queue_command(state, 42)

    assert success is True
    assert "has been assigned as reviewer" not in response
    assert "remains designated as reviewer" in response
    assert len(captured_comments) == 1
    assert captured_comments[0]["body"] == reviewer_bot.REVIEWER_REQUEST_422_TEMPLATE.format(reviewer="alice")


def test_handle_issue_or_pr_opened_pr_request_422_posts_truthful_message(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["ISSUE_AUTHOR"] = "dana"
    os.environ["ISSUE_LABELS"] = '["coding guideline"]'
    os.environ["IS_PULL_REQUEST"] = "true"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "alice")
    monkeypatch.setattr(
        reviewer_bot,
        "request_reviewer_assignment",
        lambda *args, **kwargs: reviewer_bot.AssignmentAttempt(success=False, status_code=422),
    )

    handled = reviewer_bot.handle_issue_or_pr_opened(state)

    assert handled is True
    assert len(captured_comments) == 1
    assert captured_comments[0]["body"] == reviewer_bot.REVIEWER_REQUEST_422_TEMPLATE.format(reviewer="alice")


def test_handle_issue_or_pr_opened_assigns_reviewer(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["ISSUE_AUTHOR"] = "dana"
    os.environ["ISSUE_LABELS"] = "[\"coding guideline\"]"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "alice")
    handled = reviewer_bot.handle_issue_or_pr_opened(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "assigned to review" in captured_comments[0]["body"]


def test_handle_issue_or_pr_opened_assigns_reviewer_for_fls_audit(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["ISSUE_AUTHOR"] = "dana"
    os.environ["ISSUE_LABELS"] = "[\"fls-audit\"]"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "alice")
    handled = reviewer_bot.handle_issue_or_pr_opened(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "assigned to review" in captured_comments[0]["body"]


def test_handle_issue_or_pr_opened_missing_label(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["ISSUE_AUTHOR"] = "dana"
    os.environ["ISSUE_LABELS"] = "[]"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    handled = reviewer_bot.handle_issue_or_pr_opened(state)
    assert handled is False
    assert captured_comments == []


def test_handle_labeled_event_assigns_reviewer(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["LABEL_NAME"] = "coding guideline"
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["ISSUE_AUTHOR"] = "dana"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "alice")
    handled = reviewer_bot.handle_labeled_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "assigned to review" in captured_comments[0]["body"]


def test_handle_labeled_event_assigns_reviewer_for_fls_audit(stub_api, captured_comments, monkeypatch):
    state = make_state()
    os.environ["LABEL_NAME"] = "fls-audit"
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["ISSUE_AUTHOR"] = "dana"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda *args, **kwargs: [])
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "alice")
    handled = reviewer_bot.handle_labeled_event(state)
    assert handled is True
    assert len(captured_comments) == 1
    assert "assigned to review" in captured_comments[0]["body"]


def test_handle_labeled_event_wrong_label(stub_api, captured_comments):
    state = make_state()
    os.environ["LABEL_NAME"] = "not-it"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_labeled_event(state)
    assert handled is False
    assert captured_comments == []


def test_handle_labeled_event_sign_off_marks_completion(stub_api):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["LABEL_NAME"] = "sign-off: create pr"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_labeled_event(state)
    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is not None
    assert review_data["review_completed_by"] == "alice"
    assert review_data["review_completion_source"] == "issue_label: sign-off: create pr"


def test_handle_labeled_event_sign_off_ignored_for_pr(stub_api):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["LABEL_NAME"] = "sign-off: create pr"
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["IS_PULL_REQUEST"] = "true"
    handled = reviewer_bot.handle_labeled_event(state)
    assert handled is False
    review_data = state["active_reviews"]["42"]
    assert review_data.get("review_completed_at") is None


def test_handle_rectify_command_allows_assigned_reviewer(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    monkeypatch.setattr(
        reviewer_bot,
        "reconcile_active_review_entry",
        lambda *args, **kwargs: ("ok", True, True),
    )

    message, success, state_changed = reviewer_bot.handle_rectify_command(state, 42, "alice")

    assert message == "ok"
    assert success is True
    assert state_changed is True


def test_handle_rectify_command_allows_triage(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        reviewer_bot,
        "reconcile_active_review_entry",
        lambda *args, **kwargs: ("ok", True, False),
    )

    message, success, state_changed = reviewer_bot.handle_rectify_command(state, 42, "bob")

    assert message == "ok"
    assert success is True
    assert state_changed is False


def test_handle_rectify_command_denies_unauthorized(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: False)

    message, success, state_changed = reviewer_bot.handle_rectify_command(state, 42, "bob")

    assert success is False
    assert state_changed is False
    assert "Only the assigned reviewer" in message


def test_reconcile_active_review_entry_marks_complete_for_approved(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": "2000-01-02T00:00:00+00:00",
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["IS_PULL_REQUEST"] = "true"
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "state": "COMMENTED",
                "submitted_at": "2026-02-01T00:00:00Z",
                "user": {"login": "alice"},
            },
            {
                "state": "APPROVED",
                "submitted_at": "2026-02-02T00:00:00Z",
                "user": {"login": "alice"},
            },
        ],
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: True)

    message, success, state_changed = reviewer_bot.reconcile_active_review_entry(state, 42)

    assert success is True
    assert state_changed is True
    assert "applied approval transitions" in message
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is not None
    assert review_data["review_completed_by"] == "alice"
    assert review_data["review_completion_source"] == "rectify:reconcile-pr-review"
    assert review_data["transition_warning_sent"] is None


@pytest.mark.parametrize("latest_state", ["COMMENTED", "CHANGES_REQUESTED"])
def test_reconcile_active_review_entry_updates_activity_for_non_approval(monkeypatch, latest_state):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": "2000-01-02T00:00:00+00:00",
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["IS_PULL_REQUEST"] = "true"
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "state": latest_state,
                "submitted_at": "2026-02-02T00:00:00Z",
                "user": {"login": "alice"},
            }
        ],
    )

    message, success, state_changed = reviewer_bot.reconcile_active_review_entry(state, 42)

    assert success is True
    assert state_changed is True
    assert latest_state in message
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is None
    assert review_data["transition_warning_sent"] is None
    assert review_data["last_reviewer_activity"] != "2000-01-01T00:00:00+00:00"


def test_reconcile_active_review_entry_ignores_non_assigned_reviews(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": None,
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["IS_PULL_REQUEST"] = "true"
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "state": "APPROVED",
                "submitted_at": "2026-02-02T00:00:00Z",
                "user": {"login": "bob"},
            }
        ],
    )

    message, success, state_changed = reviewer_bot.reconcile_active_review_entry(state, 42)

    assert success is True
    assert state_changed is False
    assert "No review by assigned reviewer @alice" in message
    assert state["active_reviews"]["42"]["review_completed_at"] is None


def test_reconcile_active_review_entry_idempotent_when_already_completed(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": None,
        "review_completed_at": "2000-01-02T00:00:00+00:00",
        "review_completed_by": "alice",
        "review_completion_source": "pull_request_review",
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["IS_PULL_REQUEST"] = "true"

    called = {"api": False}

    def should_not_be_called(*args, **kwargs):
        called["api"] = True
        return []

    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", should_not_be_called)

    message, success, state_changed = reviewer_bot.reconcile_active_review_entry(state, 42)

    assert success is True
    assert state_changed is False
    assert "already marked complete" in message
    assert called["api"] is False


def test_reconcile_active_review_entry_missing_entry_returns_noop():
    state = make_state()

    message, success, state_changed = reviewer_bot.reconcile_active_review_entry(state, 42)

    assert success is True
    assert state_changed is False
    assert "No active review entry exists" in message


def test_resolve_workflow_run_pr_number_from_artifact_context(monkeypatch):
    os.environ["WORKFLOW_RUN_RECONCILE_PR_NUMBER"] = "42"
    os.environ["WORKFLOW_RUN_RECONCILE_HEAD_SHA"] = "abc123"
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "abc123"

    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "abc123"}}
        if method == "GET" and endpoint == "pulls/42"
        else None,
    )

    assert reviewer_bot.resolve_workflow_run_pr_number() == 42


def test_resolve_workflow_run_pr_number_missing_artifact_env_raises():
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "abc123"

    with pytest.raises(RuntimeError, match="Missing WORKFLOW_RUN_RECONCILE_PR_NUMBER"):
        reviewer_bot.resolve_workflow_run_pr_number()


def test_resolve_workflow_run_pr_number_sha_mismatch_raises():
    os.environ["WORKFLOW_RUN_RECONCILE_PR_NUMBER"] = "42"
    os.environ["WORKFLOW_RUN_RECONCILE_HEAD_SHA"] = "abc123"
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "def456"

    with pytest.raises(RuntimeError, match="SHA mismatch"):
        reviewer_bot.resolve_workflow_run_pr_number()


def test_resolve_workflow_run_pr_number_pr_head_sha_mismatch_raises(monkeypatch):
    os.environ["WORKFLOW_RUN_RECONCILE_PR_NUMBER"] = "42"
    os.environ["WORKFLOW_RUN_RECONCILE_HEAD_SHA"] = "abc123"
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "abc123"

    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "def456"}}
        if method == "GET" and endpoint == "pulls/42"
        else None,
    )

    with pytest.raises(RuntimeError, match="head SHA does not match"):
        reviewer_bot.resolve_workflow_run_pr_number()


def test_handle_workflow_run_event_reconciles_approval(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": "2000-01-02T00:00:00+00:00",
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["WORKFLOW_RUN_EVENT"] = "pull_request_review"
    os.environ["WORKFLOW_RUN_RECONCILE_PR_NUMBER"] = "42"
    os.environ["WORKFLOW_RUN_RECONCILE_HEAD_SHA"] = "abc123"
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "abc123"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "abc123"}}
        if method == "GET" and endpoint == "pulls/42"
        else {},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "state": "APPROVED",
                "submitted_at": "2026-02-02T00:00:00Z",
                "user": {"login": "alice"},
            }
        ],
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: True)

    posted_comments = []

    def record_comment(issue_number, body):
        posted_comments.append((issue_number, body))
        return True

    monkeypatch.setattr(reviewer_bot, "post_comment", record_comment)

    handled = reviewer_bot.handle_workflow_run_event(state)

    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is not None
    assert review_data["review_completed_by"] == "alice"
    assert review_data["review_completion_source"] == "workflow_run:pull_request_review"
    assert len(posted_comments) == 1
    assert posted_comments[0][0] == 42
    assert "Rectified PR #42" in posted_comments[0][1]


def test_handle_workflow_run_event_idempotent_when_review_already_complete(monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "review_completed_at": "2000-01-02T00:00:00+00:00",
        "review_completed_by": "alice",
        "review_completion_source": "workflow_run:pull_request_review",
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["WORKFLOW_RUN_EVENT"] = "pull_request_review"
    os.environ["WORKFLOW_RUN_RECONCILE_PR_NUMBER"] = "42"
    os.environ["WORKFLOW_RUN_RECONCILE_HEAD_SHA"] = "abc123"
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "abc123"

    called = {"reviews": False, "comment": False}

    def should_not_fetch_reviews(*args, **kwargs):
        called["reviews"] = True
        return []

    def should_not_post_comment(*args, **kwargs):
        called["comment"] = True
        return True

    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "abc123"}}
        if method == "GET" and endpoint == "pulls/42"
        else {},
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", should_not_fetch_reviews)
    monkeypatch.setattr(reviewer_bot, "post_comment", should_not_post_comment)

    handled = reviewer_bot.handle_workflow_run_event(state)

    assert handled is False
    assert called["reviews"] is False
    assert called["comment"] is False


def test_handle_workflow_run_event_comment_failure_is_non_fatal(monkeypatch, capsys):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": "2000-01-02T00:00:00+00:00",
        "review_completed_at": None,
        "review_completed_by": None,
        "review_completion_source": None,
        "assignment_method": "round-robin",
        "skipped": [],
    }
    os.environ["WORKFLOW_RUN_EVENT"] = "pull_request_review"
    os.environ["WORKFLOW_RUN_RECONCILE_PR_NUMBER"] = "42"
    os.environ["WORKFLOW_RUN_RECONCILE_HEAD_SHA"] = "abc123"
    os.environ["WORKFLOW_RUN_HEAD_SHA"] = "abc123"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "abc123"}}
        if method == "GET" and endpoint == "pulls/42"
        else {},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "state": "APPROVED",
                "submitted_at": "2026-02-02T00:00:00Z",
                "user": {"login": "alice"},
            }
        ],
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: False)

    handled = reviewer_bot.handle_workflow_run_event(state)

    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is not None
    assert review_data["review_completion_source"] == "workflow_run:pull_request_review"
    captured = capsys.readouterr()
    assert (
        "WARNING: Workflow_run reconcile changed state but failed to post comment "
        "on pull request #42." in captured.err
    )


def test_handle_workflow_run_event_raises_on_invalid_context():
    state = make_state()
    os.environ["WORKFLOW_RUN_EVENT"] = "pull_request_review"

    with pytest.raises(RuntimeError, match="Missing WORKFLOW_RUN_RECONCILE_PR_NUMBER"):
        reviewer_bot.handle_workflow_run_event(state)


def test_handle_workflow_run_event_ignores_non_review_events():
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["WORKFLOW_RUN_EVENT"] = "pull_request_target"

    handled = reviewer_bot.handle_workflow_run_event(state)

    assert handled is False
    assert state["active_reviews"]["42"].get("review_completed_at") is None


def test_handle_pull_request_review_event_approval_marks_complete(stub_api):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = "approved"
    os.environ["REVIEW_AUTHOR"] = "alice"
    handled = reviewer_bot.handle_pull_request_review_event(state)
    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is not None
    assert review_data["review_completed_by"] == "alice"
    assert review_data["review_completion_source"] == "pull_request_review"
    assert review_data["last_reviewer_activity"] != "2000-01-01T00:00:00+00:00"


def test_read_level_designated_approval_triggers_mandatory_escalation(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = "approved"
    os.environ["REVIEW_AUTHOR"] = "alice"
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: False)

    handled = reviewer_bot.handle_pull_request_review_event(state)

    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["review_completed_at"] is not None
    assert review_data["mandatory_approver_required"] is True
    assert review_data["mandatory_approver_pinged_at"] is not None
    assert any(
        c["body"] == reviewer_bot.MANDATORY_TRIAGE_ESCALATION_TEMPLATE
        for c in captured_comments
    )


def test_read_level_escalation_comment_posts_once_per_review_cycle(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = "approved"
    os.environ["REVIEW_AUTHOR"] = "alice"
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda *args, **kwargs: False)

    assert reviewer_bot.handle_pull_request_review_event(state) is True
    assert reviewer_bot.handle_pull_request_review_event(state) is False

    escalation_comments = [
        c for c in captured_comments if c["body"] == reviewer_bot.MANDATORY_TRIAGE_ESCALATION_TEMPLATE
    ]
    assert len(escalation_comments) == 1


def test_triage_approval_clears_mandatory_escalation(
    stub_api, captured_comments, monkeypatch
):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "mandatory_approver_required": True,
        "mandatory_approver_pinged_at": "2026-02-11T10:00:00+00:00",
        "mandatory_approver_label_applied_at": "2026-02-11T10:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = "approved"
    os.environ["REVIEW_AUTHOR"] = "bob"

    removed = {"called": False}

    def fake_remove_label(issue_number, label):
        removed["called"] = True
        assert issue_number == 42
        assert label == reviewer_bot.MANDATORY_TRIAGE_APPROVER_LABEL
        return True

    monkeypatch.setattr(
        reviewer_bot,
        "check_user_permission",
        lambda username, required_permission="triage": username.lower() == "bob",
    )
    monkeypatch.setattr(reviewer_bot, "remove_label_with_status", fake_remove_label)

    handled = reviewer_bot.handle_pull_request_review_event(state)

    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["mandatory_approver_required"] is False
    assert review_data["mandatory_approver_satisfied_by"] == "bob"
    assert review_data["mandatory_approver_satisfied_at"] is not None
    assert removed["called"] is True
    assert any(
        c["body"] == reviewer_bot.MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver="bob")
        for c in captured_comments
    )


@pytest.mark.parametrize("review_state", ["commented", "changes_requested"])
def test_handle_pull_request_review_event_updates_activity(stub_api, review_state):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": "2000-01-02T00:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = review_state
    os.environ["REVIEW_AUTHOR"] = "alice"
    handled = reviewer_bot.handle_pull_request_review_event(state)
    assert handled is True
    review_data = state["active_reviews"]["42"]
    assert review_data["last_reviewer_activity"] != "2000-01-01T00:00:00+00:00"
    assert review_data.get("review_completed_at") is None
    assert review_data.get("transition_warning_sent") is None


def test_handle_pull_request_review_event_ignores_non_assigned(stub_api):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = "approved"
    os.environ["REVIEW_AUTHOR"] = "bob"
    handled = reviewer_bot.handle_pull_request_review_event(state)
    assert handled is False
    review_data = state["active_reviews"]["42"]
    assert review_data.get("review_completed_at") is None


def test_handle_pull_request_review_event_cross_repo_defers(stub_api):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    os.environ["ISSUE_NUMBER"] = "42"
    os.environ["REVIEW_STATE"] = "approved"
    os.environ["REVIEW_AUTHOR"] = "alice"
    os.environ["PR_IS_CROSS_REPOSITORY"] = "true"

    handled = reviewer_bot.handle_pull_request_review_event(state)

    assert handled is False
    assert state["active_reviews"]["42"].get("review_completed_at") is None


def test_handle_closed_event_clears_active_review():
    state = make_state()
    state["active_reviews"]["42"] = {"current_reviewer": "alice"}
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_closed_event(state)
    assert handled is True
    assert "42" not in state["active_reviews"]


def test_process_pass_until_expirations_restores_member(monkeypatch):
    state = make_state()
    state["queue"] = []
    state["pass_until"] = [
        {"github": "alice", "name": "Alice", "return_date": "2000-01-01"},
    ]
    updated_state, restored = reviewer_bot.process_pass_until_expirations(state)
    assert restored == ["alice"]
    assert updated_state["queue"][0]["github"] == "alice"
    assert updated_state["pass_until"] == []


def test_check_overdue_reviews_detects_warning():
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    overdue = reviewer_bot.check_overdue_reviews(state)
    assert overdue
    assert overdue[0]["needs_warning"] is True


def test_check_overdue_reviews_skips_completed():
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "review_completed_at": "2000-01-02T00:00:00+00:00",
    }
    overdue = reviewer_bot.check_overdue_reviews(state)
    assert overdue == []


def test_handle_overdue_review_warning_posts_comment(stub_api, captured_comments):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
    }
    handled = reviewer_bot.handle_overdue_review_warning(state, 42, "alice")
    assert handled is True
    assert len(captured_comments) == 1
    assert "Review Reminder" in captured_comments[0]["body"]


def test_handle_transition_notice_posts_comment(stub_api, captured_comments):
    state = make_state()
    handled = reviewer_bot.handle_transition_notice(state, 42, "alice")
    assert handled is True
    assert len(captured_comments) == 1
    assert "Transition Period Ended" in captured_comments[0]["body"]


def test_handle_scheduled_check_posts_transition(stub_api, captured_comments, monkeypatch):
    state = make_state()
    state["active_reviews"]["42"] = {
        "current_reviewer": "alice",
        "assigned_at": "2000-01-01T00:00:00+00:00",
        "last_reviewer_activity": "2000-01-01T00:00:00+00:00",
        "transition_warning_sent": "2000-01-02T00:00:00+00:00",
        "skipped": [],
    }
    monkeypatch.setattr(reviewer_bot, "get_next_reviewer", lambda *args, **kwargs: "bob")
    handled = reviewer_bot.handle_scheduled_check(state)
    assert handled is True
    assert any("Transition Period Ended" in c["body"] for c in captured_comments)


def test_handle_comment_event_malformed_known_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot pass"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "Did you mean" in captured_comments[0]["body"]


def test_handle_comment_event_malformed_unknown_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot whatever"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "Unknown command" in captured_comments[0]["body"]


def test_handle_comment_event_unknown_command(stub_api, captured_comments):
    state = make_state()
    os.environ["COMMENT_BODY"] = "@guidelines-bot /nope"
    os.environ["COMMENT_AUTHOR"] = "alice"
    os.environ["ISSUE_NUMBER"] = "42"
    handled = reviewer_bot.handle_comment_event(state)
    assert handled is False
    assert len(captured_comments) == 1
    assert "Unknown command" in captured_comments[0]["body"]


def test_classify_event_intent_cross_repo_review_is_non_mutating_defer(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_same_repo_review_is_mutating(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "false")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_MUTATING


def test_main_cross_repo_review_does_not_acquire_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")

    acquire_called = {"value": False}

    def fail_if_called():
        acquire_called["value"] = True
        raise AssertionError("acquire_state_issue_lease_lock should not be called")

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fail_if_called)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda: make_state())
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.main()

    assert acquire_called["value"] is False


def test_main_same_repo_review_acquires_lock(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "pull_request_review")
    monkeypatch.setenv("EVENT_ACTION", "submitted")
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "false")

    acquire_called = {"value": False}

    def fake_acquire():
        acquire_called["value"] = True
        return reviewer_bot.LeaseContext(
            lock_token="token",
            lock_owner_run_id="run",
            lock_owner_workflow="workflow",
            lock_owner_job="job",
            state_issue_url="https://example.com/issues/314",
            lock_ref="refs/heads/reviewer-bot-state-lock",
            lock_expires_at="2999-01-01T00:00:00+00:00",
        )

    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", fake_acquire)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_pull_request_review_event", lambda state: False)

    reviewer_bot.main()

    assert acquire_called["value"] is True


def test_main_fails_when_save_state_fails(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "handle_comment_event", lambda state: True)
    monkeypatch.setattr(reviewer_bot, "save_state", lambda state: False)

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1


def test_main_workflow_run_fails_closed_on_invalid_context(monkeypatch):
    monkeypatch.setenv("EVENT_NAME", "workflow_run")
    monkeypatch.setenv("EVENT_ACTION", "completed")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    monkeypatch.setattr(reviewer_bot, "load_state", lambda: make_state())
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda state: (state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda state: (state, []))

    with pytest.raises(SystemExit) as excinfo:
        reviewer_bot.main()

    assert excinfo.value.code == 1
