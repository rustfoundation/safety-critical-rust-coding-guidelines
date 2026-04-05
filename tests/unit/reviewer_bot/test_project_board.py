from scripts.reviewer_bot_lib import project_board, reviews
from scripts.reviewer_bot_lib.config import (
    REVIEWER_BOARD_FIELD_NEEDS_ATTENTION,
    REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED,
    REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR,
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
)
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import (
    accept_reviewer_comment,
    accept_reviewer_review,
    issue_snapshot,
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
    valid_reviewer_board_metadata,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi


def _runtime(monkeypatch, routes=None):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    if routes is not None:
        runtime.github.stub(routes)
    return runtime


def test_reviewer_board_preflight_validates_manifest(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.set_config_value("REVIEWER_BOARD_ENABLED", "true")
    runtime.set_config_value("REVIEWER_BOARD_TOKEN", "board-token")
    runtime.github_graphql = lambda query, variables=None, *, token=None: valid_reviewer_board_metadata()

    preflight = project_board.reviewer_board_preflight(runtime)

    assert preflight.enabled is True
    assert preflight.valid is True
    assert preflight.project_id == "PVT_kwDOB"


def test_reviewer_board_preflight_is_disabled_without_runtime_flag(monkeypatch):
    runtime = _runtime(monkeypatch)

    preflight = project_board.reviewer_board_preflight(runtime)

    assert preflight.enabled is False
    assert preflight.valid is True
    assert preflight.project_id is None


def test_preview_board_projection_valid_manifest_yields_preview_output(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-20T12:34:56Z", active_cycle_started_at="2026-03-20T12:34:56Z")
    runtime = _runtime(monkeypatch)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "open_tracked_assigned"
    assert preview.eligible is True
    assert preview.desired is not None
    assert preview.desired.review_state == "Awaiting Reviewer"
    assert preview.desired.reviewer == "alice"


def test_preview_board_projection_tracked_unassigned_maps_to_unassigned(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42)
    runtime = _runtime(monkeypatch)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "open_tracked_unassigned"
    assert preview.desired is not None
    assert preview.desired.review_state == "Unassigned"
    assert preview.desired.reviewer is None


def test_preview_board_projection_closed_item_maps_to_archive_intent(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    runtime = _runtime(monkeypatch)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="closed")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "closed"
    assert preview.desired is not None
    assert preview.desired.archive is True
    assert preview.desired.ensure_membership is False


def test_preview_board_projection_open_untracked_maps_to_archive_intent(monkeypatch):
    state = make_state()
    runtime = _runtime(monkeypatch)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "open_untracked"
    assert preview.desired is not None
    assert preview.desired.archive is True


def test_preview_board_projection_formats_dates_at_day_granularity(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-20T12:34:56Z", active_cycle_started_at="2026-03-20T12:34:56Z")
    accept_reviewer_comment(review, semantic_key="issue_comment:1", timestamp="2026-03-21T08:00:00Z", actor="alice")
    accept_reviewer_review(review, semantic_key="pull_request_review:10", timestamp="2026-03-21T08:00:00Z", actor="alice", reviewed_head_sha="head-1", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1"))
    routes.add_pull_request_reviews(42, [])
    runtime = _runtime(monkeypatch, routes)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-21T08:00:00Z",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.assigned_at == "2026-03-20"
    assert preview.desired.waiting_since == "2026-03-21"


def test_preview_board_projection_keeps_parity_with_refreshed_live_review_state(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-17T09:00:00Z", active_cycle_started_at="2026-03-17T09:00:00Z")
    accept_reviewer_review(review, semantic_key="pull_request_review:99", timestamp="2026-03-17T11:00:00Z", actor="alice", reviewed_head_sha="head-0", source_precedence=1)
    routes = RouteGitHubApi().add_pull_request_snapshot(42, pull_request_payload(42, head_sha="head-1")).add_pull_request_reviews(
        42,
        [
            review_payload(10, state="COMMENTED", submitted_at="2026-03-17T10:01:00Z", commit_id="head-1", author="alice"),
            review_payload(99, state="COMMENTED", submitted_at="2026-03-17T11:00:00Z", commit_id="head-0", author="alice"),
        ],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.get_user_permission_status = lambda username, required_permission="push": "granted"

    desired_labels, _ = reviews.project_status_labels_for_item(runtime, 42, state)
    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert desired_labels == {STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert preview.desired is not None
    assert preview.desired.review_state == REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR


def test_preview_board_projection_marks_projection_repair_as_attention(monkeypatch):
    state = make_state()
    make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-20T12:34:56Z",
        active_cycle_started_at="2026-03-20T12:34:56Z",
        repair_needed={"kind": "projection_failure", "reason": "projection_failed"},
    )
    runtime = _runtime(monkeypatch)
    runtime.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED


def test_reviewer_board_manifest_includes_projection_repair_attention_option():
    options = project_board.REVIEWER_BOARD_PROJECT_MANIFEST[REVIEWER_BOARD_FIELD_NEEDS_ATTENTION]["options"]

    assert REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED in options
