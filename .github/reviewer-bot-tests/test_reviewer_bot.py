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
        "ISSUE_NUMBER",
        "ISSUE_AUTHOR",
        "IS_PULL_REQUEST",
        "REVIEW_AUTHOR",
        "REVIEW_STATE",
        "REPO_OWNER",
        "REPO_NAME",
    }
    with pytest.MonkeyPatch().context() as monkeypatch:
        for name in env_vars:
            monkeypatch.delenv(name, raising=False)
        yield


@pytest.fixture
def stub_api(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api", lambda *args, **kwargs: {})
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "assign_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_pr_reviewer", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_assignee", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda *args, **kwargs: {"a", "b"})
    monkeypatch.setattr(reviewer_bot, "add_label", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "remove_label", lambda *args, **kwargs: True)
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

    def capture_api(method, endpoint, data=None):
        payload["method"] = method
        payload["endpoint"] = endpoint
        payload["data"] = data
        return {"ok": True}

    monkeypatch.setattr(reviewer_bot, "github_api", capture_api)
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 314)
    state = make_state()
    assert reviewer_bot.save_state(state) is True
    assert payload["method"] == "PATCH"
    assert payload["endpoint"] == "issues/314"
    assert "```yaml" in payload["data"]["body"]


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


def test_github_api_error_handling(monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, content):
            self.status_code = status_code
            self.content = content
            self.text = "error"

        def json(self):
            return {"ok": True}

    monkeypatch.setattr(reviewer_bot, "get_github_token", lambda: "token")
    monkeypatch.setenv("REPO_OWNER", "owner")
    monkeypatch.setenv("REPO_NAME", "repo")

    def fake_request(*args, **kwargs):
        return FakeResponse(500, b"error")

    monkeypatch.setattr(reviewer_bot.requests, "request", fake_request)
    assert reviewer_bot.github_api("GET", "issues/1") is None


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
    assert "Available Commands" in captured_comments[0]["body"]


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
