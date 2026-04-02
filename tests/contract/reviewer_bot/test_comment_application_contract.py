import pytest

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_application
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state

pytestmark = pytest.mark.contract


def test_comment_application_digest_is_stable_for_replay_identity():
    assert comment_application.digest_comment_body("hello\r\nworld\n") == comment_application.digest_comment_body("hello\nworld")


def test_comment_application_records_contributor_freshness_from_typed_request(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="dana",
        comment_body="plain text",
    )

    changed = comment_application.record_conversation_freshness(reviewer_bot, state, request)

    assert changed is True
    assert review["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:100"


def test_comment_application_stores_pending_privileged_command_from_typed_request(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="dana",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )
    harness.runtime.parse_issue_labels = lambda: [reviewer_bot.FLS_AUDIT_LABEL]
    harness.runtime.get_user_permission_status = lambda username, required_permission="triage": "granted"
    harness.runtime.post_comment = lambda issue_number, body: True

    changed = comment_application.process_comment_event(
        harness.runtime,
        state,
        request,
        classify_comment_payload=reviewer_bot.comment_routing_module.classify_comment_payload,
        classify_issue_comment_actor=reviewer_bot.comment_routing_module.classify_issue_comment_actor,
    )

    assert changed is True
    assert review["pending_privileged_commands"]["issue_comment:100"]["command_name"] == "accept-no-fls-changes"
