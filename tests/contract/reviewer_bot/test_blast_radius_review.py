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
        "change one reconcile runtime collaborator seam",
        "change one workflow-run transaction result field",
    ]


def test_f3_representative_changes_do_not_cross_core_and_legacy_owners_unnecessarily():
    review = _load_review()
    expected = {entry["change"]: entry["expected_files"] for entry in review["representative_changes"]}

    assert expected["change reviewer-response derivation"] == [
        "scripts/reviewer_bot_core/reviewer_response_policy.py",
        "tests/unit/reviewer_bot/test_reviewer_response_equivalence.py",
        "tests/unit/reviewer_bot/test_reviews_live_fetch.py",
    ]
    assert expected["change mandatory approver escalation"] == [
        "scripts/reviewer_bot_core/mandatory_approver_policy.py",
        "scripts/reviewer_bot_lib/reviews.py",
        "tests/unit/reviewer_bot/test_mandatory_approver_policy_equivalence.py",
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
    assert expected["change one reconcile runtime collaborator seam"] == [
        "scripts/reviewer_bot_lib/context.py",
        "scripts/reviewer_bot_lib/runtime.py",
        "scripts/reviewer_bot_lib/bootstrap_runtime.py",
        "tests/fixtures/fake_runtime.py",
        "tests/contract/reviewer_bot/test_adapter_contract.py",
        "tests/contract/reviewer_bot/test_fake_runtime_contract.py",
        "tests/contract/reviewer_bot/test_runtime_protocols.py",
    ]
    assert expected["change one workflow-run transaction result field"] == [
        "scripts/reviewer_bot_lib/reconcile.py",
        "scripts/reviewer_bot_lib/app.py",
        "tests/integration/reviewer_bot/test_app_execution.py",
        "tests/integration/reviewer_bot/test_app_workflow_run_bookkeeping.py",
        "tests/integration/reviewer_bot/test_app_workflow_run_paths.py",
    ]


def test_f3_blast_radius_review_matches_current_owner_locations():
    mandatory_approver_policy_text = Path("scripts/reviewer_bot_core/mandatory_approver_policy.py").read_text(encoding="utf-8")
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")
    reviewer_response_policy_text = Path("scripts/reviewer_bot_core/reviewer_response_policy.py").read_text(encoding="utf-8")
    replay_text = Path("scripts/reviewer_bot_core/reconcile_replay_policy.py").read_text(encoding="utf-8")
    command_text = Path("scripts/reviewer_bot_core/comment_command_policy.py").read_text(encoding="utf-8")

    assert "return reviewer_response_policy.compute_reviewer_response_state(" in reviews_text
    assert "def compute_reviewer_response_state(" in reviewer_response_policy_text
    assert "mandatory_approver_policy.decide_mandatory_approver_escalation(" in reviews_text
    assert "mandatory_approver_policy.decide_mandatory_approver_satisfaction(" in reviews_text
    assert "def decide_mandatory_approver_escalation(" in mandatory_approver_policy_text
    assert "def decide_comment_replay(" in replay_text
    assert "def decide_comment_command(" in command_text


def test_o5_final_proof_artifact_classification_is_explicit():
    review = _load_review()

    assert review["surviving_final_proof_artifacts"] == [
        {
            "path": "tests/contract/reviewer_bot/test_blast_radius_review.py",
            "reason": "active blast-radius risk for future change",
        },
        {
            "path": "tests/fixtures/equivalence/blast_radius/review.json",
            "reason": "active blast-radius risk for future change",
        },
        {
            "path": "tests/contract/reviewer_bot/test_runtime_protocols.py",
            "reason": "active runtime/bootstrap/fake-runtime compatibility safety",
        },
        {
            "path": "tests/contract/reviewer_bot/test_adapter_contract.py",
            "reason": "active runtime/bootstrap/fake-runtime compatibility safety",
        },
        {
            "path": "tests/contract/reviewer_bot/test_fake_runtime_contract.py",
            "reason": "active runtime/bootstrap/fake-runtime compatibility safety",
        },
    ]
    assert review["retired_migration_only_artifacts"] == [
        {
            "path": "tests/contract/reviewer_bot/test_support_layer_ownership.py",
            "reason": "migration-only ownership inventory proof superseded by final blast-radius and deletion manifests",
        },
        {
            "path": "tests/fixtures/equivalence/support_layer/symbol_inventory.json",
            "reason": "migration-only importer inventory refreshed for cleanup and no longer needed as final architecture proof",
        },
        {
            "path": "tests/fixtures/equivalence/runtime_surface/triple_inventory.json",
            "reason": "migration-only runtime inventory refreshed for cleanup and superseded by final runtime compatibility contracts",
        },
    ]
