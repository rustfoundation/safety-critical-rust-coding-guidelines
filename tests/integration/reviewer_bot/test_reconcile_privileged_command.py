import os

import pytest

pytestmark = pytest.mark.integration

from scripts.reviewer_bot_lib import automation, maintenance, review_state
from scripts.reviewer_bot_lib.config import FLS_AUDIT_LABEL
from tests.fixtures.commands_harness import CommandHarness
from tests.fixtures.reviewer_bot import make_state


def test_execute_pending_privileged_command_revalidates_live_state(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    monkeypatch.setattr(automation, "handle_accept_no_fls_changes_command", lambda bot, issue_number, actor, request=None: ("ok", True))

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"

def test_execute_pending_privileged_command_passes_revalidated_typed_request(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    monkeypatch.setenv("ISSUE_LABELS", '["stale-label"]')
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"

    observed = {}

    def fake_handle(issue_number, actor, request=None):
        observed["issue_number"] = issue_number
        observed["actor"] = actor
        observed["request"] = request
        return ("ok", True)

    monkeypatch.setattr(automation, "handle_accept_no_fls_changes_command", lambda bot, issue_number, actor, request=None: fake_handle(issue_number, actor, request))

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    request = observed["request"]
    assert observed["issue_number"] == 42
    assert observed["actor"] == "alice"
    assert request is not None
    assert request.issue_number == 42
    assert request.actor == "alice"
    assert request.command_name == "accept-no-fls-changes"
    assert request.is_pull_request is False
    assert request.issue_labels == (FLS_AUDIT_LABEL,)
    assert os.environ["ISSUE_LABELS"] == '["stale-label"]'
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"


def test_execute_pending_privileged_command_does_not_leak_issue_labels_env(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    monkeypatch.delenv("ISSUE_LABELS", raising=False)
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    monkeypatch.setattr(automation, "handle_accept_no_fls_changes_command", lambda bot, issue_number, actor, request=None: ("ok", True))

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert "ISSUE_LABELS" not in os.environ

def test_execute_pending_privileged_command_fails_closed_without_live_fls_audit_label(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    harness.runtime.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": "status: awaiting reviewer response"}]}
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    called = {"handle": 0}
    monkeypatch.setattr(
        automation,
        "handle_accept_no_fls_changes_command",
        lambda bot, issue_number, actor, request=None: called.__setitem__("handle", called["handle"] + 1) or ("ok", True),
    )

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert called["handle"] == 0
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result"] == "live_revalidation_failed"
