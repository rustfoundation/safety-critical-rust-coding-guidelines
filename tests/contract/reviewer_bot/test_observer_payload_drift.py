import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

from scripts.reviewer_bot_lib import reconcile_payloads


def _load_contract_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/workflow_contracts/observer_payload_contract_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def _load_fixture(relative_path: str) -> dict:
    return json.loads(Path(relative_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture_path", "expected_event_name", "expected_event_action"),
    [
        ("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json", "issue_comment", "created"),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
            "pull_request_review",
            "submitted",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
            "pull_request_review",
            "dismissed",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
            "pull_request_review_comment",
            "created",
        ),
    ],
)
def test_workflow_emitted_payload_fixtures_match_parseable_identity_contract(
    fixture_path, expected_event_name, expected_event_action
):
    fixture = _load_fixture(fixture_path)
    payload = fixture["payload"]
    metadata = fixture["fixture_metadata"]
    parsed = reconcile_payloads.parse_deferred_context_payload(payload)

    assert metadata["contract_class"] == "workflow_emitted_payload"
    assert metadata["contract_source"] == "workflow YAML"
    assert payload["source_event_name"] == expected_event_name
    assert payload["source_event_action"] == expected_event_action
    assert parsed.identity.source_event_name == expected_event_name
    assert parsed.identity.source_event_action == expected_event_action
    assert parsed.identity.source_run_id == payload["source_run_id"]
    assert parsed.identity.source_run_attempt == payload["source_run_attempt"]
    assert parsed.raw_payload == payload


@pytest.mark.parametrize(
    ("fixture_path",),
    [
        ("tests/fixtures/observer_payloads/helper_pr_comment_trusted_direct_noop.json",),
        ("tests/fixtures/observer_payloads/helper_pr_comment_automation_noop.json",),
    ],
)
def test_python_helper_output_fixtures_remain_parseable_migration_examples(fixture_path):
    fixture = _load_fixture(fixture_path)
    payload = fixture["payload"]
    metadata = fixture["fixture_metadata"]
    parsed = reconcile_payloads.parse_deferred_context_payload(payload)

    assert metadata["contract_class"] == "python_helper_output"
    assert metadata["contract_source"] == "production Python helper"
    assert payload["kind"] == "observer_noop"
    assert parsed.reason
    assert parsed.raw_payload == payload


def test_observer_contract_matrix_uses_final_top_level_sections_and_row_schema():
    matrix = _load_contract_matrix()

    assert set(matrix) == {"behavior_questions", "payload_contracts"}
    assert all(
        set(item) == {"question_id", "owner", "source_event_name", "source_event_action", "payload_kind"}
        for item in matrix["behavior_questions"]
    )
    assert all(
        set(item)
        == {"payload_kind", "owner", "schema_version", "carried_edge_fields", "debug_only_fields"}
        for item in matrix["payload_contracts"]
    )
    assert {item["payload_kind"] for item in matrix["payload_contracts"]} == {
        "deferred_comment",
        "deferred_review_submitted",
        "deferred_review_dismissed",
        "deferred_review_comment",
    }
    assert "observer_noop" not in {item["payload_kind"] for item in matrix["payload_contracts"]}


def test_observer_contract_matrix_rows_track_only_retained_payload_contracts():
    matrix = _load_contract_matrix()

    assert matrix["behavior_questions"]
    assert matrix["payload_contracts"]
    assert all(item["schema_version"] == 3 for item in matrix["payload_contracts"])
    assert all(item["owner"].startswith(".github/workflows/") for item in matrix["behavior_questions"])
    assert all(item["owner"].startswith(".github/workflows/") for item in matrix["payload_contracts"])
