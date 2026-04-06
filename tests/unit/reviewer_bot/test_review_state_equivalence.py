from pathlib import Path


def test_review_state_equivalence_harness_shell_and_fixture_inventory_exist():
    assert Path("tests/fixtures/equivalence/review_state/api_inventory.md").exists()
    assert Path("tests/fixtures/equivalence/review_state/local_state_only_scenarios.json").exists()
    assert Path("tests/fixtures/equivalence/review_state/live_read_assisted_scenarios.json").exists()


def test_review_state_equivalence_harness_shell_documents_future_scope():
    module_text = Path("tests/unit/reviewer_bot/test_review_state_equivalence.py").read_text(
        encoding="utf-8"
    )

    assert "local_state_only_scenarios.json" in module_text
    assert "live_read_assisted_scenarios.json" in module_text
