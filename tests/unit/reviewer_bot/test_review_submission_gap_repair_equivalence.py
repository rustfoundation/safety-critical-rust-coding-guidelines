import json
from pathlib import Path

from scripts.reviewer_bot_core import deferred_gap_diagnosis


def _load_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/review_submission_gap_repair/scenario_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def test_h4a_review_submission_gap_matrix_freezes_exact_visible_review_repair_outputs():
    matrix = _load_matrix()

    assert matrix["harness_id"] == "H4a review-submitted gap repair flow equivalence"
    scenario = matrix["scenarios"][0]

    recommendation = deferred_gap_diagnosis.recommend_visible_review_repair(
        {"current_reviewer": "alice"},
        {
            "id": 202,
            "submitted_at": "2026-03-25T11:00:00Z",
            "commit_id": "head-1",
            "user": {"login": "alice"},
        },
        "pull_request_review:202",
        current_cycle_boundary=deferred_gap_diagnosis.parse_timestamp("2026-03-17T09:00:00Z"),
    )

    assert scenario["expected_reason"] is None
    assert scenario["expected_diagnostic_reason"] is None
    assert scenario["expected_repair_category"] == "review_submission_repair"
    assert recommendation == (
        scenario["expected_recommendation_payload"]["author"],
        scenario["expected_recommendation_payload"]["submitted_at"],
        scenario["expected_recommendation_payload"]["commit_id"],
    )


def test_h4b_review_submission_gap_recommendation_flow_moves_to_core_owner():
    matrix = _load_matrix()
    scenario = matrix["scenarios"][0]

    recommendation = deferred_gap_diagnosis.recommend_review_submission_gap_repair(
        {"current_reviewer": "alice"},
        {
            "id": 202,
            "submitted_at": "2026-03-25T11:00:00Z",
            "commit_id": "head-1",
            "user": {"login": "alice"},
        },
        "pull_request_review:202",
        artifact_status="artifact_missing",
        current_cycle_boundary=deferred_gap_diagnosis.parse_timestamp("2026-03-17T09:00:00Z"),
    )
    sweeper_text = Path("scripts/reviewer_bot_lib/sweeper.py").read_text(encoding="utf-8")

    assert recommendation == {
        "category": scenario["expected_repair_category"],
        "payload": scenario["expected_recommendation_payload"],
    }
    assert "deferred_gap_diagnosis.recommend_review_submission_gap_repair(" in sweeper_text
    assert "artifact_status != \"exact_artifact_match\"" not in sweeper_text
