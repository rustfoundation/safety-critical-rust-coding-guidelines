import json
import os

import pytest

pytestmark = pytest.mark.integration

from scripts.reviewer_bot_lib import maintenance, review_state
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
    harness.runtime.handle_accept_no_fls_changes_command = lambda issue_number, actor: ("ok", True)

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"

def test_execute_pending_privileged_command_hydrates_issue_labels_for_executor(monkeypatch):
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

    observed = {}

    def fake_handle(issue_number, actor):
        observed["issue_number"] = issue_number
        observed["actor"] = actor
        observed["issue_labels"] = json.loads(os.environ["ISSUE_LABELS"])
        return ("ok", True)

    harness.runtime.handle_accept_no_fls_changes_command = fake_handle

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert observed == {
        "issue_number": 42,
        "actor": "alice",
        "issue_labels": [FLS_AUDIT_LABEL],
    }
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"

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
    harness.runtime.handle_accept_no_fls_changes_command = lambda issue_number, actor: called.__setitem__("handle", called["handle"] + 1) or ("ok", True)

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert called["handle"] == 0
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result"] == "live_revalidation_failed"
