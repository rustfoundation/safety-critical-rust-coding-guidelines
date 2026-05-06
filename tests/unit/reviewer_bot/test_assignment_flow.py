from scripts.reviewer_bot_core import comment_command_policy
from scripts.reviewer_bot_lib import assignment_flow, review_state
from scripts.reviewer_bot_lib.config import AssignmentAttempt
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_builders import build_assignment_request


def test_assignment_command_authorization_freezes_r_question_matrix():
    specific = comment_command_policy.authorize_assignment_command(
        comment_command_policy.OrdinaryCommandId.ASSIGN_SPECIFIC.value,
        actor="bob",
        issue_number=42,
        target="alice",
        current_reviewer=None,
        actor_permission="denied",
    )
    unassigned_queue = comment_command_policy.authorize_assignment_command(
        comment_command_policy.OrdinaryCommandId.ASSIGN_FROM_QUEUE.value,
        actor="bob",
        issue_number=42,
        target="producers",
        current_reviewer=None,
        actor_permission="denied",
    )
    assigned_queue_denied = comment_command_policy.authorize_assignment_command(
        comment_command_policy.OrdinaryCommandId.ASSIGN_FROM_QUEUE.value,
        actor="bob",
        issue_number=42,
        target="producers",
        current_reviewer="alice",
        actor_permission="denied",
    )
    current_reviewer_rotation = comment_command_policy.authorize_assignment_command(
        comment_command_policy.OrdinaryCommandId.ASSIGN_FROM_QUEUE.value,
        actor="alice",
        issue_number=42,
        target="producers",
        current_reviewer="alice",
        actor_permission="denied",
    )
    triage_override = comment_command_policy.authorize_assignment_command(
        comment_command_policy.OrdinaryCommandId.ASSIGN_SPECIFIC.value,
        actor="triager",
        issue_number=42,
        target="alice",
        current_reviewer="bob",
        actor_permission="granted",
    )

    assert specific.authorized is False
    assert specific.reason == "actor_not_authorized"
    assert unassigned_queue.authorized is True
    assert unassigned_queue.reason == "unassigned_queue_request"
    assert assigned_queue_denied.authorized is False
    assert assigned_queue_denied.reason == "actor_not_authorized"
    assert current_reviewer_rotation.authorized is True
    assert current_reviewer_rotation.reason == "assigned_reviewer_pass_semantics"
    assert triage_override.authorized is True
    assert triage_override.reason == "triage_override"


def test_reviewer_assignment_confirmation_covers_pr_retention_and_mismatch_statuses(monkeypatch):
    request = build_assignment_request(issue_number=42, issue_author="dana", is_pull_request=True)
    api_422 = assignment_flow.derive_reviewer_assignment_confirmation(
        request,
        reviewer="alice",
        assignment_method="manual",
        previous_reviewer=None,
        live_before=(),
        live_after=("bob",),
        assignment_attempt=AssignmentAttempt(False, 422, failure_kind="validation_failed"),
        removal_attempts={},
        same_reviewer_noop=False,
        guidance_emitted=True,
    )
    absent_live_request = assignment_flow.derive_reviewer_assignment_confirmation(
        request,
        reviewer="alice",
        assignment_method="manual",
        previous_reviewer=None,
        live_before=(),
        live_after=(),
        assignment_attempt=AssignmentAttempt(True, 201),
        removal_attempts={},
        same_reviewer_noop=False,
        guidance_emitted=True,
    )
    mismatch = assignment_flow.derive_reviewer_assignment_confirmation(
        request,
        reviewer="alice",
        assignment_method="manual",
        previous_reviewer="carol",
        live_before=(),
        live_after=("bob",),
        assignment_attempt=AssignmentAttempt(False, 409, failure_kind="conflict"),
        removal_attempts={},
        same_reviewer_noop=False,
        guidance_emitted=False,
    )

    assert api_422.assignment_write_status == "state_tracked_after_api_422"
    assert api_422.state_tracking_allowed is True
    assert absent_live_request.assignment_write_status == "state_tracked_without_live_request"
    assert absent_live_request.state_tracking_allowed is True
    assert mismatch.assignment_write_status == "blocked_final_mismatch"
    assert mismatch.state_tracking_allowed is False

    bot = FakeReviewerBotRuntime(monkeypatch)
    state = make_state()
    assert assignment_flow.apply_reviewer_assignment_confirmation(
        bot,
        state,
        request,
        api_422,
        pr_head_sha="head-1",
        record_assignment=False,
        emit_guidance=False,
    ) is True
    review = review_state.ensure_review_entry(state, 42)
    assert review["current_reviewer"] == "alice"
    assert review["active_head_sha"] == "head-1"


def test_reviewer_authority_resolution_uses_control_plane_snapshot(monkeypatch):
    snapshot = assignment_flow.build_review_control_plane_snapshot(
        {
            "number": 42,
            "pull_request": {},
            "requested_reviewers": [{"login": "alice"}],
            "assignees": [],
            "user": {"login": "dana"},
            "reviewDecision": "REVIEW_REQUIRED",
            "head": {"sha": "head-1"},
        },
        tracked_reviewer="alice",
    )
    resolution = assignment_flow.derive_reviewer_authority_resolution(snapshot)

    assert snapshot.to_output()["requested_reviewers"] == ["alice"]
    assert snapshot.to_output()["review_decision"] == "REVIEW_REQUIRED"
    assert snapshot.to_output()["head_sha"] == "head-1"
    assert resolution.authority_status == "tracked_reviewer_confirmed"
    assert resolution.reason == "present_in_live_control_plane"

    bot = FakeReviewerBotRuntime(monkeypatch)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    bot.github.get_issue_assignees_result = lambda issue_number, is_pull_request=None: bot.GitHubApiResult(
        200,
        ["bob"],
        {},
        "ok",
        True,
        None,
        0,
        None,
    )

    legacy = assignment_flow.resolve_reviewer_authority(bot, 42, review, is_pull_request=True)

    assert legacy["authority_status"] == "control_plane_mismatch"
    assert legacy["live_control_plane_reviewers"] == ["bob"]


def test_same_reviewer_assignment_confirmation_is_noop(monkeypatch):
    request = build_assignment_request(issue_number=42, issue_author="dana", is_pull_request=True)
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review.update(
        {
            "current_reviewer": "alice",
            "assigned_at": "2026-03-17T09:00:00Z",
            "active_cycle_started_at": "2026-03-17T09:00:00Z",
            "active_head_sha": "head-old",
        }
    )
    before = dict(review)
    confirmation = assignment_flow.derive_reviewer_assignment_confirmation(
        request,
        reviewer="alice",
        assignment_method="claim",
        previous_reviewer="alice",
        live_before=("alice",),
        live_after=("alice",),
        assignment_attempt=AssignmentAttempt(True, 201),
        removal_attempts={},
        same_reviewer_noop=True,
        guidance_emitted=False,
    )

    changed = assignment_flow.apply_reviewer_assignment_confirmation(
        FakeReviewerBotRuntime(monkeypatch),
        state,
        request,
        confirmation,
        pr_head_sha="head-new",
        record_assignment=True,
        emit_guidance=True,
    )

    assert changed is False
    assert confirmation.assignment_write_status == "already_live_assigned"
    assert review == before
