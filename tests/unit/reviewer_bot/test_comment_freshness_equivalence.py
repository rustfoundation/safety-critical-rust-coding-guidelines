import json
from pathlib import Path

from scripts.reviewer_bot_core import comment_freshness_policy
from scripts.reviewer_bot_lib import comment_application, review_state
from tests.fixtures.comment_routing_harness import CommentRoutingHarness
from tests.fixtures.reviewer_bot import make_state


def _load_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/comment_freshness/scenario_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def _legacy_record_conversation_freshness(state: dict, request) -> bool:
    issue_number = request.issue_number
    review_data = review_state.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    comment_author = request.comment_author
    created_at = request.comment_created_at
    semantic_key = request.comment_source_event_key or f"issue_comment:{request.comment_id}"
    if request.issue_author and request.issue_author.lower() == comment_author.lower():
        return review_state.accept_channel_event(
            review_data,
            "contributor_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
    current_reviewer = review_data.get("current_reviewer")
    if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():
        changed = review_state.accept_channel_event(
            review_data,
            "reviewer_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
        previous_activity = review_data.get("last_reviewer_activity")
        previous_warning = review_data.get("transition_warning_sent")
        previous_notice = review_data.get("transition_notice_sent_at")
        review_state.record_reviewer_activity(review_data, created_at)
        activity_changed = (
            previous_activity != review_data.get("last_reviewer_activity")
            or previous_warning != review_data.get("transition_warning_sent")
            or previous_notice != review_data.get("transition_notice_sent_at")
        )
        return changed or activity_changed
    return False


def test_comment_freshness_fixture_declares_exact_scenarios():
    matrix = _load_matrix()

    assert matrix["harness_id"] == "D1a comment freshness equivalence"
    assert matrix["scenarios"] == [
        "contributor_plain_text_freshness",
        "reviewer_plain_text_freshness",
        "reviewer_activity_only_when_semantic_key_exists",
        "non_contributor_non_reviewer_noop",
        "command_plus_text_freshness",
    ]


def test_comment_freshness_policy_decisions_match_frozen_branching_cases(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    review = review_state.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    contributor_request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="dana",
        comment_body="hello",
    )
    reviewer_request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="alice",
        comment_body="hello",
    )
    other_request = harness.request(
        issue_number=42,
        is_pull_request=False,
        issue_author="dana",
        comment_author="zoe",
        comment_body="hello",
    )

    assert comment_freshness_policy.decide_comment_freshness(review, contributor_request).channel_name == "contributor_comment"
    assert comment_freshness_policy.decide_comment_freshness(review, reviewer_request).channel_name == "reviewer_comment"
    assert comment_freshness_policy.decide_comment_freshness(review, reviewer_request).update_reviewer_activity is True
    assert comment_freshness_policy.decide_comment_freshness(review, other_request).kind == "noop"


def test_comment_freshness_equivalence_matches_legacy_mutation_and_activity_behavior(monkeypatch):
    matrix = _load_matrix()
    harness = CommentRoutingHarness(monkeypatch)

    scenarios = [
        (
            "contributor_plain_text_freshness",
            lambda state: harness.request(issue_number=42, is_pull_request=False, issue_author="dana", comment_author="dana", comment_body="hello"),
            lambda review: None,
        ),
        (
            "reviewer_plain_text_freshness",
            lambda state: harness.request(issue_number=42, is_pull_request=False, issue_author="dana", comment_author="alice", comment_body="hello", comment_created_at="2026-03-17T10:00:00Z"),
            lambda review: review.__setitem__("current_reviewer", "alice"),
        ),
        (
            "reviewer_activity_only_when_semantic_key_exists",
            lambda state: harness.request(issue_number=42, is_pull_request=False, issue_author="dana", comment_author="alice", comment_body="hello", comment_id=100, comment_created_at="2026-03-17T10:00:00Z", comment_source_event_key="issue_comment:100"),
            lambda review: (
                review.__setitem__("current_reviewer", "alice"),
                review.__setitem__("last_reviewer_activity", "2026-03-17T09:00:00Z"),
                review.__setitem__("transition_warning_sent", "2026-03-18T00:00:00Z"),
                review.__setitem__("transition_notice_sent_at", "2026-03-25T00:00:00Z"),
                review_state.accept_channel_event(review, "reviewer_comment", semantic_key="issue_comment:100", timestamp="2026-03-17T09:00:00Z", actor="alice"),
            ),
        ),
        (
            "non_contributor_non_reviewer_noop",
            lambda state: harness.request(issue_number=42, is_pull_request=False, issue_author="dana", comment_author="zoe", comment_body="hello"),
            lambda review: review.__setitem__("current_reviewer", "alice"),
        ),
        (
            "command_plus_text_freshness",
            lambda state: harness.request(issue_number=42, is_pull_request=False, issue_author="dana", comment_author="dana", comment_body="hello\n@guidelines-bot /queue"),
            lambda review: None,
        ),
    ]

    assert matrix["scenarios"] == [name for name, _req, _prep in scenarios]

    for scenario_name, make_request, prepare_review in scenarios:
        legacy_state = make_state()
        new_state = make_state()
        legacy_review = review_state.ensure_review_entry(legacy_state, 42, create=True)
        new_review = review_state.ensure_review_entry(new_state, 42, create=True)
        assert legacy_review is not None and new_review is not None
        if prepare_review is not None:
            prepare_review(legacy_review)
            prepare_review(new_review)
        request = make_request(new_state)

        legacy_changed = _legacy_record_conversation_freshness(legacy_state, request)
        new_changed = comment_application.record_conversation_freshness(harness.runtime, new_state, request)

        assert new_changed == legacy_changed, scenario_name
        assert new_state == legacy_state, scenario_name
