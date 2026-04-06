from pathlib import Path

import pytest

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
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    harness.runtime.set_config_value("ISSUE_LABELS", f'["{FLS_AUDIT_LABEL}"]')
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    harness.runtime.post_comment = lambda issue_number, body: True

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=comment_routing.classify_comment_payload,
        classify_issue_comment_actor=comment_routing.classify_issue_comment_actor,
    )

    assert changed is True
    assert review["pending_privileged_commands"]["issue_comment:100"]["command_name"] == "accept-no-fls-changes"


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
        comment_author="alice",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    harness.runtime.set_config_value("ISSUE_LABELS", f'["{FLS_AUDIT_LABEL}"]')
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    harness.runtime.post_comment = lambda issue_number, body: posted.append((issue_number, body)) or True

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=comment_routing.classify_comment_payload,
        classify_issue_comment_actor=comment_routing.classify_issue_comment_actor,
    )

    assert changed is True
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert list(pending) == [
        "source_event_key",
        "command_name",
        "issue_number",
        "actor",
        "args",
        "status",
        "created_at",
        "authorization",
        "target",
    ]
    assert posted == [
        (
            42,
            "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. Use the isolated privileged workflow to execute it from issue `#314` state.",
        )
    ]


def test_c3b2_comment_application_deletion_manifest_leaves_only_privileged_branching():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert 'if decision["kind"] == "deferred_privileged_handoff":' in module_text
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


def test_c3b2_comment_application_is_cleanup_only_for_ordinary_command_decision():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "decision = comment_command_policy.decide_comment_command(" in module_text
    assert "if decision[\"kind\"] == \"handler_call\":" in module_text
    assert "if decision[\"kind\"] == \"deferred_privileged_handoff\":" in module_text


def test_comment_application_no_longer_owns_privileged_handoff_validation_or_metadata_shaping():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "privileged_command_policy.validate_accept_no_fls_changes_handoff(" in module_text
    assert "privileged_command_policy.build_pending_privileged_command(" in module_text
    assert 'return decision.kind == "handoff_allowed", dict(decision.metadata or {})' in module_text


def test_comment_application_no_longer_owns_direct_comment_freshness_decision_branching():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "comment_freshness_policy.decide_comment_freshness(review_data, request)" in module_text
    assert "if request.issue_author and request.issue_author.lower() == comment_author.lower():" not in module_text
    assert "if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():" not in module_text


def test_d1b_comment_application_remaining_branches_are_classification_driven_application_only():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert "comment_class = classified[\"comment_class\"]" in module_text
    assert 'if comment_class in {"plain_text", "command_plus_text"} and comment_id > 0:' in module_text
    assert 'if comment_class in {"command_only", "command_plus_text"} and int(classified.get("command_count", 0)) == 1:' in module_text
    assert "if command == " not in module_text
    assert "if request.issue_author and request.issue_author.lower() == comment_author.lower():" not in module_text
