from pathlib import Path

import pytest

from scripts.reviewer_bot_core import comment_command_policy
from scripts.reviewer_bot_lib import comment_application, comment_routing, review_state
from scripts.reviewer_bot_lib.config import FLS_AUDIT_LABEL
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.contract


def test_comment_application_digest_is_stable_for_replay_identity():
    assert comment_application.digest_comment_body("hello\r\nworld\n") == comment_application.digest_comment_body("hello\nworld")


def test_comment_application_records_contributor_freshness_from_typed_request(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="dana",
        comment_body="plain text",
    )

    changed = comment_application.record_conversation_freshness(harness.runtime, state, request)

    assert changed is True
    assert review["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:100"


def test_comment_application_stores_pending_privileged_command_from_typed_request(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        issue_labels=(FLS_AUDIT_LABEL,),
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"
    harness.runtime.github.post_comment = lambda issue_number, body: True

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=comment_routing.classify_comment_payload,
        classify_issue_comment_actor=comment_routing.classify_issue_comment_actor,
    )

    assert changed is True
    assert review["sidecars"]["pending_privileged_commands"]["issue_comment:100"]["command_name"] == "accept-no-fls-changes"


def test_comment_application_freezes_pending_privileged_command_metadata_shape_and_ack_message(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    posted = []
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        issue_labels=(FLS_AUDIT_LABEL,),
        comment_author="alice",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    harness.runtime.set_config_value("STATE_ISSUE_NUMBER", "314")
    harness.runtime.github.get_user_permission_status = lambda username, required_permission="triage": "granted"
    harness.runtime.github.post_comment = lambda issue_number, body: posted.append((issue_number, body)) or True

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=comment_routing.classify_comment_payload,
        classify_issue_comment_actor=comment_routing.classify_issue_comment_actor,
    )

    assert changed is True
    pending = review["sidecars"]["pending_privileged_commands"]["issue_comment:100"]
    assert list(pending) == [
        "source_event_key",
        "command_name",
        "issue_number",
        "actor",
        "authorization_required_permission",
        "authorization_authorized",
        "target_kind",
        "target_number",
        "target_labels_snapshot",
        "status",
        "created_at",
        "completed_at",
        "result_code",
        "result_message",
        "opened_pr_url",
    ]
    assert posted == [
        (
            42,
            "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. Use the isolated privileged workflow to execute it from issue `#314` state.",
        )
    ]


def test_c3b2_comment_application_deletion_manifest_leaves_only_privileged_branching():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "DeferPrivilegedHandoffDecision" in module_text
    assert "ORDINARY_COMMAND_HANDLERS" in module_text
    assert "decision.command_id" in module_text
    for command_name in [
        '"pass"',
        '"away"',
        '"label"',
        '"sync-members"',
        '"queue"',
        '"commands"',
        '"claim"',
        '"release"',
        '"rectify"',
        '"r?-user"',
        '"assign-from-queue"',
        '"_multiple_commands"',
        '"_malformed_known"',
        '"_malformed_unknown"',
    ]:
        assert f"command == {command_name}" not in module_text


def test_n1_comment_application_obeys_policy_selected_handler_without_inline_command_branching(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="alice",
        comment_body="@guidelines-bot /claim",
    )
    calls = []

    monkeypatch.setattr(
        comment_command_policy,
        "decide_comment_command",
        lambda *args, **kwargs: comment_command_policy.ExecuteOrdinaryCommandDecision(
            command_id=comment_command_policy.OrdinaryCommandId.QUEUE,
            issue_number=42,
            actor="alice",
            raw_args=(),
            needs_assignment_request=False,
        ),
    )
    monkeypatch.setattr(
        comment_application.commands_module,
        "handle_queue_command",
        lambda bot, current_state: calls.append((bot, current_state)) or ("", True),
    )
    harness.runtime.github.add_reaction = lambda *args, **kwargs: True

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=lambda bot, body: {"comment_class": "command_only", "command_count": 1, "command": "claim", "args": []},
        classify_issue_comment_actor=comment_routing.classify_issue_comment_actor,
    )

    assert changed is False
    assert calls == [(harness.runtime, state)]


def test_comment_application_no_longer_owns_privileged_handoff_validation_or_metadata_shaping():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "privileged_command_policy.validate_accept_no_fls_changes_handoff(" in module_text
    assert "privileged_command_policy.build_pending_privileged_command(" in module_text
    assert "put_pending_accept_no_fls_changes" in module_text


def test_comment_application_no_longer_owns_direct_comment_freshness_decision_branching():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "comment_freshness_policy.decide_comment_freshness(review_data, request)" in module_text
    assert "if request.issue_author and request.issue_author.lower() == comment_author.lower():" not in module_text
    assert "if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():" not in module_text


def test_n1_comment_application_obeys_routing_result_without_text_shape_contract(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="dana",
        comment_body="plain text",
    )
    calls = {"freshness": 0, "command": 0}

    monkeypatch.setattr(
        comment_application,
        "_route_comment_application",
        lambda classified, *, comment_id: "freshness_only",
    )
    monkeypatch.setattr(
        comment_application,
        "record_conversation_freshness",
        lambda bot, current_state, current_request: calls.__setitem__("freshness", calls["freshness"] + 1) or True,
    )
    monkeypatch.setattr(
        comment_application,
        "apply_comment_command",
        lambda *args, **kwargs: calls.__setitem__("command", calls["command"] + 1) or False,
    )

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=lambda bot, body: {"comment_class": "plain_text", "command_count": 0, "command": None, "args": []},
        classify_issue_comment_actor=comment_routing.classify_issue_comment_actor,
    )

    assert changed is True
    assert calls == {"freshness": 1, "command": 0}
