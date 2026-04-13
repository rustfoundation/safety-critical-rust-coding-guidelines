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
    review["sidecars"]["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "authorization_required_permission": "triage",
        "authorization_authorized": True,
        "target_kind": "issue",
        "target_number": 42,
        "target_labels_snapshot": [FLS_AUDIT_LABEL],
        "status": "pending",
        "created_at": "2026-03-17T10:00:00Z",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"
    monkeypatch.setattr(
        automation,
        "handle_accept_no_fls_changes_command",
        lambda bot, issue_number, actor, execution_plan=None, request=None: automation.privileged_command_policy.CompletePrivilegedExecution(
            status="executed",
            result_code="opened_pull_request",
            result_message="ok",
        ),
    )

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert review["sidecars"]["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"

def test_execute_pending_privileged_command_passes_revalidated_typed_request(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["sidecars"]["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "authorization_required_permission": "triage",
        "authorization_authorized": True,
        "target_kind": "issue",
        "target_number": 42,
        "target_labels_snapshot": [FLS_AUDIT_LABEL],
        "status": "pending",
        "created_at": "2026-03-17T10:00:00Z",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    monkeypatch.setenv("ISSUE_LABELS", '["stale-label"]')
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"

    observed = {}

    def fake_handle(issue_number, actor, execution_plan=None):
        observed["issue_number"] = issue_number
        observed["actor"] = actor
        observed["execution_plan"] = execution_plan
        return automation.privileged_command_policy.CompletePrivilegedExecution(
            status="executed",
            result_code="opened_pull_request",
            result_message="ok",
        )

    monkeypatch.setattr(
        automation,
        "handle_accept_no_fls_changes_command",
        lambda bot, issue_number, actor, execution_plan=None, request=None: fake_handle(issue_number, actor, execution_plan),
    )

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    execution_plan = observed["execution_plan"]
    assert observed["issue_number"] == 42
    assert observed["actor"] == "alice"
    assert execution_plan is not None
    assert execution_plan.record.issue_number == 42
    assert execution_plan.record.actor == "alice"
    assert execution_plan.record.command_name == "accept-no-fls-changes"
    assert execution_plan.record.target_labels_snapshot == (FLS_AUDIT_LABEL,)
    assert os.environ["ISSUE_LABELS"] == '["stale-label"]'
    assert review["sidecars"]["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"


def test_execute_pending_privileged_command_does_not_leak_issue_labels_env(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["sidecars"]["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "authorization_required_permission": "triage",
        "authorization_authorized": True,
        "target_kind": "issue",
        "target_number": 42,
        "target_labels_snapshot": [FLS_AUDIT_LABEL],
        "status": "pending",
        "created_at": "2026-03-17T10:00:00Z",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    monkeypatch.delenv("ISSUE_LABELS", raising=False)
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": FLS_AUDIT_LABEL}]}
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"
    monkeypatch.setattr(
        automation,
        "handle_accept_no_fls_changes_command",
        lambda bot, issue_number, actor, execution_plan=None, request=None: automation.privileged_command_policy.CompletePrivilegedExecution(
            status="executed",
            result_code="opened_pull_request",
            result_message="ok",
        ),
    )

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert "ISSUE_LABELS" not in os.environ

def test_execute_pending_privileged_command_fails_closed_without_live_fls_audit_label(monkeypatch):
    harness = CommandHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["sidecars"]["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "authorization_required_permission": "triage",
        "authorization_authorized": True,
        "target_kind": "issue",
        "target_number": 42,
        "target_labels_snapshot": [FLS_AUDIT_LABEL],
        "status": "pending",
        "created_at": "2026-03-17T10:00:00Z",
    }
    harness.set_manual_dispatch(source_event_key="issue_comment:100")
    harness.runtime.github.get_issue_or_pr_snapshot = lambda issue_number: {"number": issue_number, "labels": [{"name": "status: awaiting reviewer response"}]}
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"
    called = {"handle": 0}
    monkeypatch.setattr(
        automation,
        "handle_accept_no_fls_changes_command",
        lambda bot, issue_number, actor, execution_plan=None, request=None: called.__setitem__("handle", called["handle"] + 1)
        or automation.privileged_command_policy.CompletePrivilegedExecution(
            status="executed",
            result_code="opened_pull_request",
            result_message="ok",
        ),
    )

    assert maintenance.handle_manual_dispatch(harness.runtime, state) is True
    assert called["handle"] == 0
    pending = review["sidecars"]["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result_code"] == "missing_fls_audit_label"
