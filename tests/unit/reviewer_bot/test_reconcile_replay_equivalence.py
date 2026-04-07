import json
from pathlib import Path

from scripts.reviewer_bot_core import reconcile_replay_policy


def _load_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/reconcile_replay/scenario_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def test_reconcile_replay_scenario_matrix_fixture_exists_and_names_required_rows():
    matrix = _load_matrix()

    assert matrix["harness_id"] == "C4a reconcile replay scenario matrix"
    assert [row["scenario_id"] for row in matrix["scenarios"]] == [
        "noop_artifact",
        "deferred_comment_replay_matching_live_comment",
        "deferred_comment_replay_missing_live_comment",
        "deferred_comment_replay_digest_or_classification_drift",
        "deferred_review_submitted_replay",
        "deferred_review_dismissed_replay",
        "deferred_review_comment_replay",
        "freshness_only_update",
        "fail_closed_gap_update",
    ]


def test_reconcile_replay_scenario_matrix_records_explicit_delta_gap_and_diagnostic_columns():
    matrix = _load_matrix()

    for row in matrix["scenarios"]:
        assert row["expected_state_delta"]
        assert isinstance(row["expected_touched_items"], list)
        assert row["expected_deferred_gap_mutation"]
        assert row["expected_reconciled_source_events_mutation"]
        assert row["expected_diagnostic_output"]


def test_reconcile_replay_scenario_matrix_keeps_materially_distinct_drift_cases_separate():
    matrix = _load_matrix()
    row_ids = {row["scenario_id"] for row in matrix["scenarios"]}

    assert "deferred_comment_replay_missing_live_comment" in row_ids
    assert "deferred_comment_replay_digest_or_classification_drift" in row_ids
    assert row_ids >= {"freshness_only_update", "fail_closed_gap_update", "noop_artifact"}


def test_reconcile_replay_policy_covers_noop_freshness_and_fail_closed_rows():
    noop = reconcile_replay_policy.decide_observer_noop(
        source_event_key="issue_comment:210",
        reason="trusted_direct_same_repo_human_comment",
    )
    missing_live = reconcile_replay_policy.decide_comment_replay(
        comment_id=210,
        source_comment_class="command_plus_text",
        source_has_non_command_text=True,
        source_freshness_eligible=True,
        live_comment_found=False,
        live_body_digest_matches=False,
        live_classified=None,
        live_failure_kind="not_found",
        runbook_path="runbook/path.md",
    )
    drift = reconcile_replay_policy.decide_comment_replay(
        comment_id=210,
        source_comment_class="command_only",
        source_has_non_command_text=False,
        source_freshness_eligible=False,
        live_comment_found=True,
        live_body_digest_matches=True,
        live_classified={"comment_class": "command_only", "has_non_command_text": False, "command_count": 2},
        live_failure_kind=None,
        runbook_path="runbook/path.md",
    )

    assert noop.source_event_key == "issue_comment:210"
    assert missing_live.record_source_freshness is True
    assert missing_live.failed_closed_reason == "reconcile_failed_closed"
    assert drift.failed_closed_reason == "reconcile_failed_closed"
    assert drift.record_source_freshness is False
    assert drift.replay_comment_command is False


def test_h3_reconcile_replay_policy_preserves_freshness_for_classification_drift_when_source_was_eligible():
    drift = reconcile_replay_policy.decide_comment_replay(
        comment_id=211,
        source_comment_class="plain_text",
        source_has_non_command_text=True,
        source_freshness_eligible=True,
        live_comment_found=True,
        live_body_digest_matches=True,
        live_classified={"comment_class": "command_plus_text", "has_non_command_text": True, "command_count": 1},
        live_failure_kind=None,
        runbook_path="runbook/path.md",
    )

    assert drift.record_source_freshness is True
    assert drift.failed_closed_reason == "reconcile_failed_closed"


def test_reconcile_replay_policy_covers_submitted_and_dismissed_review_rows():
    submitted = reconcile_replay_policy.decide_review_submitted_replay(
        source_event_key="pull_request_review:11",
        actor_login="alice",
        current_reviewer="alice",
        live_commit_id="head-1",
        live_submitted_at="2026-03-17T10:00:00Z",
    )
    dismissed = reconcile_replay_policy.decide_review_dismissed_replay(
        source_event_key="pull_request_review_dismissed:12",
        timestamp="2026-03-17T10:10:00Z",
    )

    assert submitted.accept_reviewer_review is True
    assert submitted.mark_reconciled is True
    assert dismissed.accept_review_dismissal is True
    assert dismissed.clear_gap is True


def test_h3_deferred_comment_replay_success_path_stays_policy_owned():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")
    policy_text = Path("scripts/reviewer_bot_core/reconcile_replay_policy.py").read_text(encoding="utf-8")

    assert "if context.payload.comment_class in {\"command_only\", \"command_plus_text\"}:" not in reconcile_text
    assert "if decision.replay_comment_command:" in reconcile_text
    assert "if decision.mark_reconciled:" in reconcile_text
    assert "if decision.clear_gap:" in reconcile_text
    assert "def decide_comment_replay(" in policy_text
