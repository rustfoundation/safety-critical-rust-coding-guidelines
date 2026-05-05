import json
from pathlib import Path

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import project_board, reviews
from scripts.reviewer_bot_lib.config import (
    REVIEWER_BOARD_FIELD_NEEDS_ATTENTION,
    REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED,
    REVIEWER_BOARD_OPTION_ATTENTION_TRANSITION_NOTICE_SENT,
    REVIEWER_BOARD_OPTION_ATTENTION_WARNING_SENT,
    REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR,
    REVIEWER_BOARD_OPTION_AWAITING_REVIEWER,
    STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL,
)
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.focused_fake_services import GraphQLTransportStub
from tests.fixtures.http_responses import FakeGitHubResponse
from tests.fixtures.reviewer_bot import (
    accept_contributor_comment,
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


def _fail_closed_review_gap(
    *,
    author="alice",
    commit_id="head-1",
    timestamp="2026-03-18T10:00:00Z",
    operator_action_required=True,
):
    return {
        "source_event_key": "pull_request_review:501",
        "source_event_kind": "pull_request_review:submitted",
        "source_event_created_at": timestamp,
        "reason": "reconcile_failed_closed",
        "operator_action_required": operator_action_required,
        "visible_review_diagnostic": {
            "category": "visible_review_without_replay_artifact",
            "payload": {
                "author": author,
                "submitted_at": timestamp,
                "commit_id": commit_id,
            },
        },
    }


def _fail_closed_normalized_review_gap(
    *,
    author="alice",
    commit_id="head-1",
    timestamp="2026-03-18T10:00:00Z",
    operator_action_required=True,
):
    return {
        "source_event_key": "pull_request_review:501",
        "source_event_kind": "pull_request_review:submitted",
        "source_event_created_at": timestamp,
        "source_actor_login": author,
        "source_commit_id": commit_id,
        "reason": "reconcile_failed_closed",
        "operator_action_required": operator_action_required,
    }


def _fail_closed_comment_gap(
    source_event_key: str,
    source_event_kind: str,
    *,
    author="alice",
    timestamp="2026-03-18T10:00:00Z",
    source_commit_id: str | None = None,
    operator_action_required=True,
):
    gap = {
        "source_event_key": source_event_key,
        "source_event_kind": source_event_kind,
        "source_event_created_at": timestamp,
        "source_actor_login": author,
        "reason": "reconcile_failed_closed",
        "operator_action_required": operator_action_required,
    }
    if source_commit_id is not None:
        gap["source_commit_id"] = source_commit_id
    return gap


def test_reviewer_board_preflight_validates_manifest(monkeypatch):
    runtime = _runtime(monkeypatch)
    runtime.set_config_value("REVIEWER_BOARD_ENABLED", "true")
    runtime.set_config_value("REVIEWER_BOARD_TOKEN", "board-token")
    runtime.graphql_transport.stub_sequence([FakeGitHubResponse(200, valid_reviewer_board_metadata(), "ok")])

    preflight = project_board.reviewer_board_preflight(runtime)

    assert preflight.enabled is True
    assert preflight.valid is True
    assert preflight.project_id == "PVT_kwDOB"


def test_bootstrapped_runtime_resolves_reviewer_board_metadata(monkeypatch):
    runtime = reviewer_bot._runtime_bot()
    runtime.set_config_value("REVIEWER_BOARD_TOKEN", "board-token")
    runtime.graphql_transport = GraphQLTransportStub()
    runtime.graphql_transport.stub_sequence([FakeGitHubResponse(200, valid_reviewer_board_metadata(), "ok")])

    metadata = project_board.resolve_project_metadata(runtime)

    assert metadata.project_id == "PVT_kwDOB"


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
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "open_tracked_assigned"
    assert preview.eligible is True
    assert preview.desired is not None
    assert preview.desired.review_state == "Awaiting Reviewer"
    assert preview.desired.reviewer == "alice"


def test_preview_board_projection_consumes_only_stable_reviewer_response_fields(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice", assigned_at="2026-03-20T12:34:56Z", active_cycle_started_at="2026-03-20T12:34:56Z")
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-21T08:00:00Z",
        "reason": "review_head_stale",
        "ignored": {"contributor_handoff": "not consumed"},
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.review_state == "Awaiting Reviewer"
    assert preview.desired.waiting_since == "2026-03-21"


def test_preview_board_projection_tracked_unassigned_maps_to_unassigned(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42)
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "open_tracked_unassigned"
    assert preview.desired is not None
    assert preview.desired.review_state == "Unassigned"
    assert preview.desired.reviewer is None


def test_preview_board_projection_closed_item_maps_to_archive_intent(monkeypatch):
    state = make_state()
    make_tracked_review_state(state, 42, reviewer="alice")
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="closed")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.classification == "closed"
    assert preview.desired is not None
    assert preview.desired.archive is True
    assert preview.desired.ensure_membership is False


def test_preview_board_projection_open_untracked_maps_to_archive_intent(monkeypatch):
    state = make_state()
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

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
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-21T08:00:00Z",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.assigned_at == "2026-03-20"
    assert preview.desired.waiting_since == "2026-03-21"


def test_preview_board_projection_non_pr_contributor_followup_returns_to_reviewer(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-20T12:34:56Z",
        active_cycle_started_at="2026-03-20T12:34:56Z",
    )
    accept_reviewer_comment(
        review,
        semantic_key="issue_comment:10",
        timestamp="2026-03-21T08:00:00Z",
        actor="alice",
    )
    accept_contributor_comment(
        review,
        semantic_key="issue_comment:11",
        timestamp="2026-03-22T09:00:00Z",
        actor="dana",
    )
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.review_state == "Awaiting Reviewer"
    assert preview.desired.waiting_since == "2026-03-22"


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
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    desired_labels, _ = reviews.project_status_labels_for_item(runtime, 42, state)
    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert desired_labels == {STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert preview.desired is not None
    assert preview.desired.review_state == REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR


def test_preview_board_projection_keeps_pr264_alternate_approval_boundary(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        264,
        reviewer="iglesias",
        assigned_at="2026-02-10T17:20:07Z",
        active_cycle_started_at="2026-02-10T17:20:07Z",
    )
    accept_reviewer_review(
        review,
        semantic_key="pull_request_review:77",
        timestamp="2026-03-18T01:09:05Z",
        actor="iglesias",
        reviewed_head_sha="head-old",
        source_precedence=1,
    )
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-04-01T00:00:00Z"
    routes = RouteGitHubApi().add_pull_request_snapshot(264, pull_request_payload(264, head_sha="head-live", author="manhatsu")).add_pull_request_reviews(
        264,
        [review_payload(501, state="APPROVED", submitted_at="2026-03-18T12:10:42Z", commit_id="head-live", author="plaindocs")],
    )
    runtime = _runtime(monkeypatch, routes)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.github.get_user_permission_status = lambda username, required_permission="push": "granted"

    preview = project_board.preview_board_projection_for_item(runtime, state, 264)

    assert preview.classification == "open_tracked_assigned"
    assert preview.desired is not None
    assert preview.desired.review_state == REVIEWER_BOARD_OPTION_AWAITING_REVIEWER
    assert preview.desired.waiting_since == "2026-02-10"
    assert preview.desired.needs_attention == "Transition Notice Sent"


def test_preview_board_projection_marks_fail_closed_current_scope_gap_as_attention(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-17T09:00:00Z",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    review["sidecars"]["deferred_gaps"]["pull_request_review:501"] = _fail_closed_review_gap()
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-17T09:00:00Z",
        "reason": "no_reviewer_activity",
        "current_head_sha": "head-1",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED


def test_preview_board_projection_marks_normalized_review_gap_as_attention(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-17T09:00:00Z",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    review["sidecars"]["deferred_gaps"]["pull_request_review:501"] = _fail_closed_normalized_review_gap()
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-17T09:00:00Z",
        "reason": "no_reviewer_activity",
        "current_head_sha": "head-1",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED


def test_preview_board_projection_marks_fail_closed_gap_as_attention_outside_reviewer_wait(monkeypatch):
    for state_name in ["done", "awaiting_contributor_response", "awaiting_write_approval"]:
        state = make_state()
        review = make_tracked_review_state(
            state,
            42,
            reviewer="alice",
            assigned_at="2026-03-17T09:00:00Z",
            active_cycle_started_at="2026-03-17T09:00:00Z",
        )
        review["sidecars"]["deferred_gaps"]["pull_request_review:501"] = _fail_closed_normalized_review_gap()
        runtime = _runtime(monkeypatch)
        runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
        runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
            "state": state_name,
            "anchor_timestamp": "2026-03-17T09:00:00Z",
            "reason": "current_scope_repair_required",
            "current_head_sha": "head-1",
        }

        preview = project_board.preview_board_projection_for_item(runtime, state, 42)

        assert preview.desired is not None
        assert preview.desired.needs_attention == REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED, state_name


def test_preview_board_projection_marks_fail_closed_comment_gaps_with_source_actor_as_attention(monkeypatch):
    cases = [
        ("issue_comment:210", "issue_comment:created", None),
        ("pull_request_review_comment:404", "pull_request_review_comment:created", "head-1"),
    ]
    for source_event_key, source_event_kind, source_commit_id in cases:
        state = make_state()
        review = make_tracked_review_state(
            state,
            42,
            reviewer="alice",
            assigned_at="2026-03-17T09:00:00Z",
            active_cycle_started_at="2026-03-17T09:00:00Z",
        )
        review["sidecars"]["deferred_gaps"][source_event_key] = _fail_closed_comment_gap(
            source_event_key,
            source_event_kind,
            source_commit_id=source_commit_id,
        )
        runtime = _runtime(monkeypatch)
        runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
        runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
            "state": "awaiting_reviewer_response",
            "anchor_timestamp": "2026-03-17T09:00:00Z",
            "reason": "no_reviewer_activity",
            "current_head_sha": "head-1",
        }

        preview = project_board.preview_board_projection_for_item(runtime, state, 42)

        assert preview.desired is not None
        assert preview.desired.needs_attention == REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED


def test_preview_board_projection_ignores_comment_gap_for_wrong_source_actor(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-17T09:00:00Z",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    review["sidecars"]["deferred_gaps"]["issue_comment:210"] = _fail_closed_comment_gap(
        "issue_comment:210",
        "issue_comment:created",
        author="bob",
    )
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-17T09:00:00Z",
        "reason": "no_reviewer_activity",
        "current_head_sha": "head-1",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == "No"


def test_preview_board_projection_ignores_review_comment_gap_without_current_head_evidence(monkeypatch):
    cases = [
        ("missing head evidence", None),
        ("wrong head", "head-2"),
    ]
    for _name, source_commit_id in cases:
        state = make_state()
        review = make_tracked_review_state(
            state,
            42,
            reviewer="alice",
            assigned_at="2026-03-17T09:00:00Z",
            active_cycle_started_at="2026-03-17T09:00:00Z",
        )
        review["sidecars"]["deferred_gaps"]["pull_request_review_comment:404"] = _fail_closed_comment_gap(
            "pull_request_review_comment:404",
            "pull_request_review_comment:created",
            source_commit_id=source_commit_id,
        )
        runtime = _runtime(monkeypatch)
        runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
        runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
            "state": "awaiting_reviewer_response",
            "anchor_timestamp": "2026-03-17T09:00:00Z",
            "reason": "no_reviewer_activity",
            "current_head_sha": "head-1",
        }

        preview = project_board.preview_board_projection_for_item(runtime, state, 42)

        assert preview.desired is not None
        assert preview.desired.needs_attention == "No", _name


def test_preview_board_projection_ignores_fail_closed_gaps_outside_current_scope(monkeypatch):
    cases = [
        ("wrong reviewer", _fail_closed_review_gap(author="bob")),
        ("wrong head", _fail_closed_review_gap(commit_id="head-2")),
        ("before anchor", _fail_closed_review_gap(timestamp="2026-03-16T10:00:00Z")),
        ("missing operator action", _fail_closed_review_gap(operator_action_required=False)),
        ("bad timestamp", _fail_closed_review_gap(timestamp="not-a-timestamp")),
    ]
    for _name, gap in cases:
        state = make_state()
        review = make_tracked_review_state(
            state,
            42,
            reviewer="alice",
            assigned_at="2026-03-17T09:00:00Z",
            active_cycle_started_at="2026-03-17T09:00:00Z",
        )
        review["sidecars"]["deferred_gaps"]["pull_request_review:501"] = gap
        runtime = _runtime(monkeypatch)
        runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
        runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
            "state": "awaiting_reviewer_response",
            "anchor_timestamp": "2026-03-17T09:00:00Z",
            "reason": "no_reviewer_activity",
            "current_head_sha": "head-1",
        }

        preview = project_board.preview_board_projection_for_item(runtime, state, 42)

        assert preview.desired is not None
        assert preview.desired.needs_attention == "No", _name


def test_preview_board_projection_ignores_raw_reminders_outside_reviewer_wait(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-17T09:00:00Z",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-04-01T00:00:00Z"
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "done",
        "anchor_timestamp": "2026-03-18T10:00:00Z",
        "reason": "write_approval_present",
        "current_head_sha": "head-1",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == "No"


def test_preview_board_projection_ignores_raw_reminders_before_reviewer_wait_anchor(monkeypatch):
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        assigned_at="2026-03-17T09:00:00Z",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-18T01:00:00Z"
    runtime = _runtime(monkeypatch)
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
    runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
        "state": "awaiting_reviewer_response",
        "anchor_timestamp": "2026-03-18T10:00:00Z",
        "reason": "contributor_comment_newer",
        "current_head_sha": "head-1",
    }

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == "No"


def test_preview_board_projection_maps_raw_reminders_at_or_after_reviewer_wait_anchor(monkeypatch):
    cases = [
        ("transition_notice_sent_at", REVIEWER_BOARD_OPTION_ATTENTION_TRANSITION_NOTICE_SENT),
        ("transition_warning_sent", REVIEWER_BOARD_OPTION_ATTENTION_WARNING_SENT),
    ]
    for field_name, expected_attention in cases:
        state = make_state()
        review = make_tracked_review_state(
            state,
            42,
            reviewer="alice",
            assigned_at="2026-03-17T09:00:00Z",
            active_cycle_started_at="2026-03-17T09:00:00Z",
        )
        review[field_name] = "2026-03-18T10:00:00Z"
        runtime = _runtime(monkeypatch)
        runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open", is_pull_request=True)
        runtime.adapters.review_state.compute_reviewer_response_state = lambda issue_number, review_data, **kwargs: {
            "state": "awaiting_reviewer_response",
            "anchor_timestamp": "2026-03-18T10:00:00Z",
            "reason": "contributor_comment_newer",
            "current_head_sha": "head-1",
        }

        preview = project_board.preview_board_projection_for_item(runtime, state, 42)

        assert preview.desired is not None
        assert preview.desired.needs_attention == expected_attention


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
    runtime.github.get_issue_or_pr_snapshot = lambda issue_number: issue_snapshot(issue_number, state="open")

    preview = project_board.preview_board_projection_for_item(runtime, state, 42)

    assert preview.desired is not None
    assert preview.desired.needs_attention == REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED


def test_reviewer_board_manifest_includes_projection_repair_attention_option():
    options = project_board.REVIEWER_BOARD_PROJECT_MANIFEST[REVIEWER_BOARD_FIELD_NEEDS_ATTENTION]["options"]

    assert REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED in options


def test_h2a_mandatory_approver_matrix_stays_focused_on_mandatory_approver_decisions():
    matrix = json.loads(
        Path("tests/fixtures/equivalence/mandatory_approver_policy/decision_matrix.json").read_text(encoding="utf-8")
    )

    assert matrix["harness_id"] == "H2a mandatory-approver decision equivalence"
    assert matrix["out_of_scope"] == [
        "reviewer-response derivation",
        "label writes outside mandatory approver decisions",
    ]
