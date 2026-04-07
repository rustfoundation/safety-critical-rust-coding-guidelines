import json
from pathlib import Path


def _load_review() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/blast_radius/review.json").read_text(encoding="utf-8")
    )


def _cards_by_id(review: dict) -> dict[str, dict]:
    return {entry["id"]: entry for entry in review["representative_changes"]}


def test_f3_blast_radius_review_records_representative_locality_cards():
    review = _load_review()
    cards = _cards_by_id(review)

    assert review["harness_id"] == "F3 blast radius review"
    assert review["locality_budgets"] == {
        "ordinary policy change": {
            "production_authority_categories": 1,
            "legacy_same_seam_authority_files": 0,
            "proof_families": 1,
        },
        "support or execution change": {
            "production_authority_categories": 2,
            "proof_families": 1,
        },
        "runtime or protocol change": {
            "production_authority_categories": 3,
            "proof_families": 2,
        },
        "orchestration or transaction change": {
            "production_authority_categories": 2,
            "proof_families": 2,
        },
    }
    assert set(cards) == {f"RC{number}" for number in range(1, 11)}

    summary = {
        card_id: {
            key: cards[card_id][key]
            for key in (
                "change",
                "change_class",
                "production_authority_categories",
                "proof_families",
                "hotspot_files",
                "semantic_inventory_entries",
                "expected_files",
            )
        }
        for card_id in sorted(cards)
    }

    assert summary == {
        "RC1": {
            "change": "reviewer-response policy rule",
            "change_class": "ordinary policy change",
            "production_authority_categories": ["core-policy"],
            "proof_families": ["unit-equivalence"],
            "hotspot_files": [],
            "semantic_inventory_entries": [
                "tests/fixtures/equivalence/reviewer_response/scenario_matrix.json"
            ],
            "expected_files": [
                "scripts/reviewer_bot_core/reviewer_response_policy.py",
                "tests/unit/reviewer_bot/test_reviewer_response_equivalence.py",
            ],
        },
        "RC10": {
            "change": "workflow-run transaction result field change",
            "change_class": "orchestration or transaction change",
            "production_authority_categories": ["execution-orchestration"],
            "proof_families": ["integration-transaction"],
            "hotspot_files": [
                "scripts/reviewer_bot_lib/reconcile.py",
                "scripts/reviewer_bot_lib/app.py",
            ],
            "semantic_inventory_entries": [],
            "expected_files": [
                "scripts/reviewer_bot_lib/reconcile.py",
                "scripts/reviewer_bot_lib/app.py",
                "tests/integration/reviewer_bot/test_app_execution.py",
                "tests/integration/reviewer_bot/test_app_workflow_run_bookkeeping.py",
                "tests/integration/reviewer_bot/test_app_workflow_run_paths.py",
            ],
        },
        "RC2": {
            "change": "live-repair rule",
            "change_class": "ordinary policy change",
            "production_authority_categories": ["core-policy"],
            "proof_families": ["unit-equivalence"],
            "hotspot_files": [],
            "semantic_inventory_entries": [
                "tests/fixtures/equivalence/review_state_live_repair/scenarios.json"
            ],
            "expected_files": [
                "scripts/reviewer_bot_core/review_state_live_repair.py",
                "tests/unit/reviewer_bot/test_review_state_equivalence.py",
            ],
        },
        "RC3": {
            "change": "approval rule",
            "change_class": "ordinary policy change",
            "production_authority_categories": ["core-policy"],
            "proof_families": ["unit-equivalence"],
            "hotspot_files": [],
            "semantic_inventory_entries": [
                "tests/fixtures/equivalence/approval_policy/in_scope_functions.json"
            ],
            "expected_files": [
                "scripts/reviewer_bot_core/approval_policy.py",
                "tests/unit/reviewer_bot/test_approval_policy_equivalence.py",
            ],
        },
        "RC4": {
            "change": "mandatory-approver policy rule",
            "change_class": "ordinary policy change",
            "production_authority_categories": ["core-policy"],
            "proof_families": ["unit-equivalence"],
            "hotspot_files": [],
            "semantic_inventory_entries": [
                "tests/fixtures/equivalence/mandatory_approver_policy/decision_matrix.json"
            ],
            "expected_files": [
                "scripts/reviewer_bot_core/mandatory_approver_policy.py",
                "tests/unit/reviewer_bot/test_mandatory_approver_policy_equivalence.py",
            ],
        },
        "RC5": {
            "change": "mandatory-approver execution flow",
            "change_class": "support or execution change",
            "production_authority_categories": ["lib-support"],
            "proof_families": ["unit-live-fetch"],
            "hotspot_files": ["scripts/reviewer_bot_lib/reviews.py"],
            "semantic_inventory_entries": [],
            "expected_files": [
                "scripts/reviewer_bot_lib/reviews.py",
                "tests/unit/reviewer_bot/test_reviews_live_fetch.py",
            ],
        },
        "RC6": {
            "change": "deferred replay fail-closed message",
            "change_class": "orchestration or transaction change",
            "production_authority_categories": ["core-policy"],
            "proof_families": ["unit-equivalence", "integration-transaction"],
            "hotspot_files": [],
            "semantic_inventory_entries": [],
            "expected_files": [
                "scripts/reviewer_bot_core/reconcile_replay_policy.py",
                "tests/unit/reviewer_bot/test_reconcile_replay_equivalence.py",
                "tests/integration/reviewer_bot/test_reconcile_workflow_run.py",
            ],
        },
        "RC7": {
            "change": "ordinary command rule",
            "change_class": "ordinary policy change",
            "production_authority_categories": ["core-policy"],
            "proof_families": ["unit-equivalence"],
            "hotspot_files": [],
            "semantic_inventory_entries": [],
            "expected_files": [
                "scripts/reviewer_bot_core/comment_command_policy.py",
                "tests/unit/reviewer_bot/test_comment_command_equivalence.py",
                "tests/unit/reviewer_bot/test_commands.py",
            ],
        },
        "RC8": {
            "change": "reconcile workflow protocol change",
            "change_class": "runtime or protocol change",
            "production_authority_categories": ["execution-orchestration", "runtime-protocol"],
            "proof_families": ["unit-equivalence", "contract-inventory"],
            "hotspot_files": [
                "scripts/reviewer_bot_lib/context.py",
                "scripts/reviewer_bot_lib/reconcile.py",
            ],
            "semantic_inventory_entries": [
                "tests/fixtures/equivalence/runtime_surface/deletion_manifest.json"
            ],
            "expected_files": [
                "scripts/reviewer_bot_lib/context.py",
                "scripts/reviewer_bot_lib/reconcile.py",
                "tests/unit/reviewer_bot/test_reconcile_unit.py",
                "tests/contract/reviewer_bot/test_runtime_protocols.py",
            ],
        },
        "RC9": {
            "change": "runtime compatibility surface change",
            "change_class": "runtime or protocol change",
            "production_authority_categories": ["runtime-protocol", "fixture-double"],
            "proof_families": ["contract-inventory"],
            "hotspot_files": [
                "scripts/reviewer_bot_lib/runtime.py",
                "scripts/reviewer_bot_lib/bootstrap_runtime.py",
                "tests/fixtures/fake_runtime.py",
                "tests/fixtures/focused_fake_services.py",
            ],
            "semantic_inventory_entries": [
                "tests/fixtures/equivalence/runtime_surface/triple_inventory.json",
                "tests/fixtures/equivalence/runtime_surface/deletion_manifest.json",
            ],
            "expected_files": [
                "scripts/reviewer_bot_lib/runtime.py",
                "scripts/reviewer_bot_lib/bootstrap_runtime.py",
                "tests/fixtures/fake_runtime.py",
                "tests/fixtures/focused_fake_services.py",
                "tests/contract/reviewer_bot/test_adapter_contract.py",
                "tests/contract/reviewer_bot/test_fake_runtime_contract.py",
                "tests/contract/reviewer_bot/test_runtime_protocols.py",
            ],
        },
    }


def test_f3_representative_changes_stay_within_locality_budgets():
    review = _load_review()
    budgets = review["locality_budgets"]

    for card in review["representative_changes"]:
        budget = budgets[card["change_class"]]
        assert len(card["production_authority_categories"]) <= budget["production_authority_categories"], card["id"]
        assert len(card["proof_families"]) <= budget["proof_families"], card["id"]
        assert set(card["hotspot_files"]).issubset(set(card["expected_files"])), card["id"]
        if card["change_class"] == "ordinary policy change":
            assert "scripts/reviewer_bot_lib/reviews.py" not in card["expected_files"], card["id"]
            assert budgets[card["change_class"]]["legacy_same_seam_authority_files"] == 0


def test_f3_blast_radius_review_matches_current_owner_locations():
    mandatory_approver_policy_text = Path("scripts/reviewer_bot_core/mandatory_approver_policy.py").read_text(encoding="utf-8")
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")
    reviewer_response_policy_text = Path("scripts/reviewer_bot_core/reviewer_response_policy.py").read_text(encoding="utf-8")
    live_repair_text = Path("scripts/reviewer_bot_core/review_state_live_repair.py").read_text(encoding="utf-8")
    helper_text = Path("scripts/reviewer_bot_core/reviewer_review_helpers.py").read_text(encoding="utf-8")
    approval_policy_text = Path("scripts/reviewer_bot_core/approval_policy.py").read_text(encoding="utf-8")
    replay_text = Path("scripts/reviewer_bot_core/reconcile_replay_policy.py").read_text(encoding="utf-8")
    command_text = Path("scripts/reviewer_bot_core/comment_command_policy.py").read_text(encoding="utf-8")

    assert "return reviewer_response_policy.compute_reviewer_response_state(" in reviews_text
    assert "approval_policy.compute_pr_approval_state_result(" in reviewer_response_policy_text
    assert "legacy_reviews.resolve_pr_approval_state(" not in reviewer_response_policy_text
    assert "reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(" in reviewer_response_policy_text
    assert "reviewer_review_helpers.build_reviewer_review_record_from_live_review(" in reviewer_response_policy_text
    assert "reviewer_review_helpers.compare_records(" in reviewer_response_policy_text
    assert "legacy_reviews.get_preferred_current_reviewer_review_for_cycle(" not in reviewer_response_policy_text
    assert "legacy_reviews.build_reviewer_review_record_from_live_review(" not in reviewer_response_policy_text
    assert "legacy_reviews._compare_records(" not in reviewer_response_policy_text
    assert "reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(" in live_repair_text
    assert "reviewer_review_helpers.build_reviewer_review_record_from_live_review(" in live_repair_text
    assert "legacy_reviews.get_preferred_current_reviewer_review_for_cycle(" not in live_repair_text
    assert "legacy_reviews.build_reviewer_review_record_from_live_review(" not in live_repair_text
    assert "mandatory_approver_policy.decide_mandatory_approver_escalation(" in reviews_text
    assert "mandatory_approver_policy.decide_mandatory_approver_satisfaction(" in reviews_text
    assert "def trigger_mandatory_approver_escalation(" in reviews_text
    assert "def satisfy_mandatory_approver_requirement(" in reviews_text
    assert "def decide_mandatory_approver_escalation(" in mandatory_approver_policy_text
    assert "def decide_mandatory_approver_satisfaction(" in mandatory_approver_policy_text
    assert "legacy_reviews._projection_failure(" in approval_policy_text
    assert "legacy_reviews._pull_request_read_result(" in approval_policy_text
    assert "legacy_reviews.get_pull_request_reviews_result(" in approval_policy_text
    assert "legacy_reviews._permission_status(" in approval_policy_text
    assert "legacy_reviews.parse_github_timestamp" in approval_policy_text
    assert "def get_preferred_current_reviewer_review_for_cycle(" in helper_text
    assert "def build_reviewer_review_record_from_live_review(" in helper_text
    assert "def compare_records(" in helper_text
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
    assert review["active_migration_proof_artifacts"] == [
        {
            "path": "tests/contract/reviewer_bot/test_support_layer_ownership.py",
            "reason": "active migration proof that still enforces support-layer ownership inventory",
        },
        {
            "path": "tests/fixtures/equivalence/support_layer/symbol_inventory.json",
            "reason": "active migration fixture still enforced by support-layer ownership contract proof",
        },
        {
            "path": "tests/fixtures/equivalence/runtime_surface/triple_inventory.json",
            "reason": "active migration fixture until runtime-surface inventory and deletion proof retire together",
        },
        {
            "path": "tests/fixtures/equivalence/runtime_surface/deletion_manifest.json",
            "reason": "active migration fixture until runtime-surface inventory and deletion proof retire together",
        },
    ]
    assert review["retired_migration_only_artifacts"] == []
