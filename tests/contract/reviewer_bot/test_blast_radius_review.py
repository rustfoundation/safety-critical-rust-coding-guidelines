import json
from pathlib import Path


def _load_review() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/blast_radius/review.json").read_text(encoding="utf-8")
    )


def test_f3_blast_radius_review_records_exact_expected_file_touch_sets():
    review = _load_review()

    assert review["harness_id"] == "F3 blast radius review"
    assert [entry["change"] for entry in review["representative_changes"]] == [
        "change reviewer-response derivation",
        "change mandatory approver escalation",
        "change deferred replay fail-closed message",
        "change one command behavior",
    ]


def test_f3_representative_changes_do_not_cross_core_and_legacy_owners_unnecessarily():
    review = _load_review()
    expected = {entry["change"]: entry["expected_files"] for entry in review["representative_changes"]}

    assert expected["change reviewer-response derivation"] == [
        "scripts/reviewer_bot_lib/reviews.py",
        "scripts/reviewer_bot_lib/reviews_projection.py",
        "tests/unit/reviewer_bot/test_reviews_projection.py",
        "tests/unit/reviewer_bot/test_reviews_live_fetch.py",
    ]
    assert expected["change mandatory approver escalation"] == [
        "scripts/reviewer_bot_lib/reviews.py",
        "tests/unit/reviewer_bot/test_reviews_live_fetch.py",
    ]
    assert expected["change deferred replay fail-closed message"] == [
        "scripts/reviewer_bot_core/reconcile_replay_policy.py",
        "tests/unit/reviewer_bot/test_reconcile_replay_equivalence.py",
        "tests/integration/reviewer_bot/test_reconcile_workflow_run.py",
    ]
    assert expected["change one command behavior"] == [
        "scripts/reviewer_bot_core/comment_command_policy.py",
        "tests/unit/reviewer_bot/test_comment_command_equivalence.py",
        "tests/unit/reviewer_bot/test_commands.py",
    ]


def test_f3_blast_radius_review_matches_current_owner_locations():
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")
    replay_text = Path("scripts/reviewer_bot_core/reconcile_replay_policy.py").read_text(encoding="utf-8")
    command_text = Path("scripts/reviewer_bot_core/comment_command_policy.py").read_text(encoding="utf-8")

    assert "def compute_reviewer_response_state(" in reviews_text
    assert "def trigger_mandatory_approver_escalation(" in reviews_text
    assert "def decide_comment_replay(" in replay_text
    assert "def decide_comment_command(" in command_text
