from pathlib import Path

import yaml
from factories import make_state, valid_reviewer_board_metadata

from scripts import reviewer_bot


def test_reviewer_board_preflight_validates_manifest(monkeypatch):
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_BOARD_TOKEN", "board-token")
    monkeypatch.setattr(reviewer_bot, "github_graphql", lambda query, variables=None, *, token=None: valid_reviewer_board_metadata())

    preflight = reviewer_bot.reviewer_board_preflight()

    assert preflight.enabled is True
    assert preflight.valid is True
    assert preflight.project_id == "PVT_kwDOB"

def test_preview_board_projection_valid_manifest_yields_preview_output(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "open_tracked_assigned"
    assert preview.eligible is True
    assert preview.desired is not None
    assert preview.desired.review_state == "Awaiting Reviewer"
    assert preview.desired.reviewer == "alice"

def test_preview_board_projection_tracked_unassigned_maps_to_unassigned(monkeypatch):
    state = make_state()
    reviewer_bot.ensure_review_entry(state, 42, create=True)
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "open_tracked_unassigned"
    assert preview.desired is not None
    assert preview.desired.review_state == "Unassigned"
    assert preview.desired.reviewer is None
    assert preview.desired.waiting_since is None
    assert preview.desired.needs_attention == "No"

def test_preview_board_projection_closed_item_maps_to_archive_intent(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "closed", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "closed"
    assert preview.eligible is False
    assert preview.desired is not None
    assert preview.desired.archive is True
    assert preview.desired.ensure_membership is False

def test_preview_board_projection_open_untracked_maps_to_archive_intent(monkeypatch):
    state = make_state()
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "open_untracked"
    assert preview.eligible is False
    assert preview.desired is not None
    assert preview.desired.archive is True

def test_preview_board_projection_formats_dates_at_day_granularity(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:1",
        timestamp="2026-03-21T08:00:00Z",
        actor="alice",
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-21T08:00:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.desired is not None
    assert preview.desired.assigned_at == "2026-03-20"
    assert preview.desired.waiting_since == "2026-03-21"

def test_preview_board_projection_keeps_parity_with_refreshed_live_review_state(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-17T09:00:00Z"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    desired_labels, _ = reviewer_bot.project_status_labels_for_item(42, state)
    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert preview.desired is not None
    assert preview.desired.review_state == reviewer_bot.REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR

def test_preview_board_projection_marks_projection_repair_as_attention(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"
    review["repair_needed"] = {
        "kind": "projection_failure",
        "reason": "projection_failed",
    }
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.desired is not None
    assert (
        preview.desired.needs_attention
        == reviewer_bot.REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED
    )

def test_sweeper_repair_workflow_exposes_reviewer_board_preview_dispatch():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8"))
    on_block = data.get("on", data.get(True))
    workflow_dispatch = on_block["workflow_dispatch"]
    action_input = workflow_dispatch["inputs"]["action"]
    assert "preview-reviewer-board" in action_input["options"]
    issue_number_input = workflow_dispatch["inputs"]["issue_number"]
    assert issue_number_input["required"] is False
    assert issue_number_input["type"] == "string"

def test_sweeper_repair_workflow_scopes_reviewer_board_env_to_preview_only():
    workflow_text = Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8")
    assert "ISSUE_NUMBER: ${{ github.event.inputs.issue_number }}" in workflow_text
    assert (
        "REVIEWER_BOARD_ENABLED: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && 'true' || 'false' }}"
        in workflow_text
    )
    assert (
        "REVIEWER_BOARD_TOKEN: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && secrets.REVIEWER_BOARD_TOKEN || '' }}"
        in workflow_text
    )

def test_reviewer_board_manifest_includes_projection_repair_attention_option():
    options = reviewer_bot.REVIEWER_BOARD_PROJECT_MANIFEST[
        reviewer_bot.REVIEWER_BOARD_FIELD_NEEDS_ATTENTION
    ]["options"]

    assert reviewer_bot.REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED in options
