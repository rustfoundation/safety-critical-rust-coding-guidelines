import json

import pytest

from scripts.reviewer_bot_core.reviewer_response_policy import (
    to_reviewer_response_decision,
)
from scripts.reviewer_bot_lib import issue314_state_health, reviews_projection
from scripts.reviewer_bot_lib.reminder_comments import scan_reviewer_reminder_comments


def _projection(
    issue_number: int,
    actual_labels: tuple[str, ...],
    state: str,
    *,
    suppresses_overdue_reminder: bool | None = None,
):
    decision_payload = {
        "issue_number": issue_number,
        "current_reviewer": "iglesias",
        "response_state": state,
        "suppression_reason": "legacy_duplicate_reminders_exhausted"
        if state == "reviewer_reassignment_needed"
        else None,
        "current_scope_key": "scope",
        "current_scope_basis": "reminder_cadence_exhausted",
    }
    if suppresses_overdue_reminder is not None:
        decision_payload["suppresses_overdue_reminder"] = suppresses_overdue_reminder
    decision = to_reviewer_response_decision(decision_payload)
    return decision, reviews_projection.derive_status_label_projection(
        reviews_projection.StatusLabelProjectionInput(
            issue_number=issue_number,
            issue_state="open",
            actual_labels=actual_labels,
            reviewer_response=decision,
            reviewer_authority_outcome="tracked_reviewer_confirmed",
            freshness_runtime_epoch="freshness_v15",
            status_projection_epoch="status_projection_v2",
        )
    )


def _repair_summary(**overrides):
    values = {
        "schema_version": 1,
        "repair_action": "repair-issue314-state-health",
        "state_issue_number": 314,
        "issue_number": 314,
        "validation_nonce": "nonce",
        "target_collection_mode": "global_issue314_state_health",
        "active_rows_inspected": (42,),
        "rows_repaired": (),
        "rows_removed_closed": (),
        "rows_operator_action_required": (),
        "rows_blocked": (),
        "status_labels_changed": (),
        "reviewer_facing_reminder_posts_attempted": 0,
        "manual_issue314_edit_status": "not_attempted",
        "state_store_mutation_mode": "not_required",
        "evaluated_repo": "rustfoundation/safety-critical-rust-coding-guidelines",
        "head_sha": "head",
        "evaluated_ref": "head",
        "workflow_path": ".github/workflows/reviewer-bot-sweeper-repair.yml",
        "run_id": "1",
        "run_attempt": "1",
        "artifact_name": "reviewer-bot-repair-output-1-attempt-1",
        "artifact_file": "issue314-state-health-repair-summary.json",
        "output_keys": (),
        "result": "already_healthy",
    }
    values.update(overrides)
    return issue314_state_health.Issue314StateHealthRepairSummary(**values)


def test_issue314_classifier_marks_pr264_stale_label_as_operator_action_without_ping_risk():
    decision, projection = _projection(
        264,
        ("status: awaiting reviewer response",),
        "reviewer_reassignment_needed",
    )
    scan = scan_reviewer_reminder_comments(
        [
            {
                "id": 4240517367,
                "created_at": "2026-04-14T00:44:23Z",
                "body": "⚠️ **Review Reminder**\n\n"
                "Hey @iglesias, it's been more than 14 days since you were assigned to review this.\n\n"
                "If no action is taken within 14 days, you may be transitioned from Producer to Observer status.",
                "user": {"login": "github-actions[bot]"},
            },
            {
                "id": 4240520000,
                "created_at": "2026-04-14T00:52:09Z",
                "body": "⚠️ **Review Reminder**\n\n"
                "Hey @iglesias, this review has already received its final transition notice.\n\n"
                "If no action is taken, the reviewer may be transitioned from Producer to Observer status.",
                "user": {"login": "github-actions[bot]"},
            },
        ]
    )
    input = issue314_state_health.Issue314StateHealthClassificationInput(
        state_issue_number=314,
        validation_nonce="nonce",
        active_review_rows=(
            {
                "issue_number": 264,
                "review_data": {
                    "current_reviewer": "iglesias",
                    "active_head_sha": "7d8864fa0c00b5bf9da20dd66047f039a049fd8b",
                },
            },
        ),
        live_snapshots={
            264: {
                "number": 264,
                "state": "open",
                "pull_request": {},
                "labels": [{"name": "status: awaiting reviewer response"}],
            }
        },
        reviewer_responses={264: decision},
        status_projections={264: projection},
        reminder_scans={264: scan},
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id="1",
        run_attempt="1",
    )

    summary = issue314_state_health.classify_issue314_state_health(input)
    payload = summary.to_output()

    assert payload["preview_action"] == "preview-issue314-state-health"
    assert payload["issue_number"] == 314
    assert payload["rows_operator_action_required"] == [264]
    assert payload["rows_blocked"] == []
    assert payload["pr264_no_ping_status"] == "pass"
    row = payload["row_inventory"][0]
    assert row["health_classification"] == "operator_action_required"
    assert row["status_label_risk"] == "operator_visible_stale"
    assert row["automated_reminder_risk"] is False
    assert payload["output_keys"] == sorted(payload.keys())


def test_issue314_classifier_blocks_pr264_handoff_when_projection_truth_is_incompatible():
    decision, projection = _projection(
        264,
        ("status: awaiting reviewer response",),
        "awaiting_contributor_response",
    )
    input = issue314_state_health.Issue314StateHealthClassificationInput(
        state_issue_number=314,
        validation_nonce="nonce",
        active_review_rows=(
            {
                "issue_number": 264,
                "review_data": {
                    "current_reviewer": "iglesias",
                    "active_head_sha": "7d8864fa0c00b5bf9da20dd66047f039a049fd8b",
                },
            },
        ),
        live_snapshots={
            264: {
                "number": 264,
                "state": "open",
                "pull_request": {},
                "labels": [{"name": "status: awaiting reviewer response"}],
            }
        },
        reviewer_responses={264: decision},
        status_projections={264: projection},
        reminder_scans={264: scan_reviewer_reminder_comments([])},
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id="1",
        run_attempt="1",
    )

    summary = issue314_state_health.classify_issue314_state_health(input)
    payload = summary.to_output()

    assert payload["rows_operator_action_required"] == []
    assert payload["rows_blocked"] == [264]
    row = payload["row_inventory"][0]
    assert row["health_classification"] == "blocked"
    assert row["classification_reason"] == "pr264_projection_handoff_response_state_mismatch"
    assert row["blockers"] == ["pr264_projection_handoff_response_state_mismatch"]


def test_issue314_classifier_keeps_aligned_awaiting_reviewer_response_healthy():
    decision, projection = _projection(
        42,
        ("status: awaiting reviewer response",),
        "awaiting_reviewer_response",
    )
    input = issue314_state_health.Issue314StateHealthClassificationInput(
        state_issue_number=314,
        validation_nonce="nonce",
        active_review_rows=({"issue_number": 42, "review_data": {"current_reviewer": "alice"}},),
        live_snapshots={
            42: {
                "number": 42,
                "state": "open",
                "pull_request": {},
                "labels": [{"name": "status: awaiting reviewer response"}],
            }
        },
        reviewer_responses={42: decision},
        status_projections={42: projection},
        reminder_scans={42: scan_reviewer_reminder_comments([])},
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id="1",
        run_attempt="1",
    )

    summary = issue314_state_health.classify_issue314_state_health(input)

    assert summary.rows_blocked == ()
    assert summary.rows_repairable == ()
    row = summary.row_inventory[0]
    assert row.health_classification == "healthy"
    assert row.automated_reminder_risk is False
    assert row.status_label_risk == "aligned"


def test_issue314_classifier_marks_awaiting_reviewer_response_label_drift_repairable():
    decision, projection = _projection(
        360,
        ("status: awaiting reviewer response", "status: draft"),
        "awaiting_reviewer_response",
    )
    input = issue314_state_health.Issue314StateHealthClassificationInput(
        state_issue_number=314,
        validation_nonce="nonce",
        active_review_rows=({"issue_number": 360, "review_data": {"current_reviewer": "alice"}},),
        live_snapshots={
            360: {
                "number": 360,
                "state": "open",
                "labels": [
                    {"name": "status: awaiting reviewer response"},
                    {"name": "status: draft"},
                ],
            }
        },
        reviewer_responses={360: decision},
        status_projections={360: projection},
        reminder_scans={360: scan_reviewer_reminder_comments([])},
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id="1",
        run_attempt="1",
    )

    summary = issue314_state_health.classify_issue314_state_health(input)

    assert summary.rows_blocked == ()
    assert summary.rows_repairable == (360,)
    row = summary.row_inventory[0]
    assert row.health_classification == "repairable"
    assert row.automated_reminder_risk is False
    assert row.status_label_risk == "repairable_drift"


def test_issue314_classifier_blocks_contradictory_non_remindable_response():
    decision, projection = _projection(
        42,
        ("status: reviewer reassignment needed",),
        "reviewer_reassignment_needed",
        suppresses_overdue_reminder=False,
    )
    input = issue314_state_health.Issue314StateHealthClassificationInput(
        state_issue_number=314,
        validation_nonce="nonce",
        active_review_rows=({"issue_number": 42, "review_data": {"current_reviewer": "alice"}},),
        live_snapshots={
            42: {
                "number": 42,
                "state": "open",
                "pull_request": {},
                "labels": [{"name": "status: reviewer reassignment needed"}],
            }
        },
        reviewer_responses={42: decision},
        status_projections={42: projection},
        reminder_scans={42: scan_reviewer_reminder_comments([])},
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-preview.yml",
        run_id="1",
        run_attempt="1",
    )

    summary = issue314_state_health.classify_issue314_state_health(input)

    assert summary.rows_blocked == (42,)
    assert summary.row_inventory[0].automated_reminder_risk is True
    assert summary.row_inventory[0].status_label_risk == "blocked_unknown"


def test_issue314_repair_summary_writer_requires_artifact_path(monkeypatch):
    monkeypatch.delenv("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", raising=False)
    summary = issue314_state_health.Issue314StateHealthRepairSummary(
        schema_version=1,
        repair_action="repair-issue314-state-health",
        state_issue_number=314,
        issue_number=314,
        validation_nonce="nonce",
        target_collection_mode="global_issue314_state_health",
        active_rows_inspected=(264,),
        rows_repaired=(),
        rows_removed_closed=(),
        rows_operator_action_required=(264,),
        rows_blocked=(),
        status_labels_changed=(),
        reviewer_facing_reminder_posts_attempted=0,
        manual_issue314_edit_status="not_attempted",
        state_store_mutation_mode="not_required",
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-sweeper-repair.yml",
        run_id="1",
        run_attempt="1",
        artifact_name="reviewer-bot-repair-output-1-attempt-1",
        artifact_file="issue314-state-health-repair-summary.json",
        output_keys=(),
        result="already_healthy",
    )

    with pytest.raises(RuntimeError, match="issue314_state_health_repair_summary_path_missing"):
        issue314_state_health.emit_issue314_state_health_repair_summary(summary)


def test_issue314_summary_requires_identity_fields():
    summary = _repair_summary(validation_nonce="")

    with pytest.raises(RuntimeError, match="issue314_state_health_identity_blocked:missing:validation_nonce"):
        summary.to_output()


def test_issue314_summary_rejects_broad_or_manual_repair_as_success():
    with pytest.raises(RuntimeError, match="target_collection_mode"):
        _repair_summary(target_collection_mode="broad").to_output()

    with pytest.raises(RuntimeError, match="manual_issue314_edit"):
        _repair_summary(manual_issue314_edit_status="attempted").to_output()


def test_issue314_summary_rejects_blocked_or_final_label_only_success():
    with pytest.raises(RuntimeError, match="blocked_rows_success"):
        _repair_summary(rows_blocked=(42,), result="changed").to_output()

    with pytest.raises(RuntimeError, match="final_label_only_status"):
        _repair_summary(status_labels_changed=(42,), rows_repaired=(), result="changed").to_output()


def test_issue314_repair_summary_writer_emits_identity_fields(monkeypatch, tmp_path):
    summary = issue314_state_health.Issue314StateHealthRepairSummary(
        schema_version=1,
        repair_action="repair-issue314-state-health",
        state_issue_number=314,
        issue_number=314,
        validation_nonce="nonce",
        target_collection_mode="global_issue314_state_health",
        active_rows_inspected=(42, 264),
        rows_repaired=(42,),
        rows_removed_closed=(),
        rows_operator_action_required=(264,),
        rows_blocked=(),
        status_labels_changed=(42,),
        reviewer_facing_reminder_posts_attempted=0,
        manual_issue314_edit_status="not_attempted",
        state_store_mutation_mode="not_required",
        evaluated_repo="rustfoundation/safety-critical-rust-coding-guidelines",
        head_sha="head",
        evaluated_ref="head",
        workflow_path=".github/workflows/reviewer-bot-sweeper-repair.yml",
        run_id="1",
        run_attempt="2",
        artifact_name="reviewer-bot-repair-output-1-attempt-2",
        artifact_file="issue314-state-health-repair-summary.json",
        output_keys=(),
        result="changed",
    )
    path = tmp_path / "repair" / "issue314-state-health-repair-summary.json"
    monkeypatch.setenv("ISSUE314_STATE_HEALTH_REPAIR_SUMMARY_PATH", str(path))

    issue314_state_health.emit_issue314_state_health_repair_summary(summary)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["target_collection_mode"] == "global_issue314_state_health"
    assert payload["reviewer_facing_reminder_posts_attempted"] == 0
    assert payload["manual_issue314_edit_status"] == "not_attempted"
    assert payload["artifact_file"] == "issue314-state-health-repair-summary.json"
    assert payload["output_keys"] == sorted(payload.keys())
