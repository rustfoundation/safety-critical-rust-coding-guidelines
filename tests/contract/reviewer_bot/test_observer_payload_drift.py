import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

from scripts.reviewer_bot_lib import comment_routing, reconcile_payloads
from tests.fixtures.comment_routing_harness import CommentRoutingHarness


def _load_contract_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/workflow_contracts/observer_payload_contract_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def _load_fixture(relative_path: str) -> dict:
    return json.loads(Path(relative_path).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("fixture_path", "expected_payload"),
    [
        (
            "tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json",
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 401,
                "source_run_attempt": 3,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:501",
                "pr_number": 42,
                "comment_id": 501,
                "comment_class": "command_plus_text",
                "has_non_command_text": True,
                "source_body_digest": "0077f0d5470f756bc8005e538a4bf62506c3d65f66ba46234a8c3b5e6ab4d082",
                "source_created_at": "2026-03-20T20:48:25Z",
                "actor_login": "contributor",
                "actor_id": 7001,
                "actor_class": "repo_user_principal",
                "source_artifact_name": "reviewer-bot-comment-context-401-attempt-3",
            },
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 402,
                "source_run_attempt": 4,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:601",
                "pr_number": 42,
                "review_id": 601,
                "source_submitted_at": "2026-03-20T20:50:00Z",
                "source_review_state": "approved",
                "source_commit_id": "abc123def456",
                "actor_login": "reviewer1",
                "actor_id": 7002,
                "source_artifact_name": "reviewer-bot-review-submitted-context-402-attempt-4",
            },
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Dismissed Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
                "source_run_id": 403,
                "source_run_attempt": 5,
                "source_event_name": "pull_request_review",
                "source_event_action": "dismissed",
                "source_event_key": "pull_request_review_dismissed:602",
                "pr_number": 42,
                "review_id": 602,
                "source_commit_id": "fedcba654321",
                "actor_login": "maintainer1",
                "actor_id": 7003,
                "source_artifact_name": "reviewer-bot-review-dismissed-context-403-attempt-5",
            },
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 404,
                "source_run_attempt": 6,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:701",
                "pr_number": 42,
                "comment_id": 701,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": "b3ea06a5981d84991c680b3a0b9a3e0bdbcbd0a52bddc7eaf79946cde1cd0f0a",
                "source_created_at": "2026-03-20T21:00:00Z",
                "actor_login": "reviewer2",
                "actor_id": 7004,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 601,
                "in_reply_to_id": None,
                "source_artifact_name": "reviewer-bot-review-comment-context-404-attempt-6",
            },
        ),
    ],
)
def test_workflow_emitted_payload_fixtures_match_frozen_contracts(fixture_path, expected_payload):
    fixture = _load_fixture(fixture_path)
    payload = fixture["payload"]
    metadata = fixture["fixture_metadata"]

    assert metadata["contract_class"] == "workflow_emitted_payload"
    assert metadata["contract_source"] == "workflow YAML"
    assert metadata["source_workflow_file"] == payload["source_workflow_file"]
    assert payload == expected_payload
    assert reconcile_payloads.parse_deferred_context_payload(payload).raw_payload == payload
    assert reconcile_payloads.expected_observer_identity(payload) == (
        payload["source_workflow_name"],
        payload["source_workflow_file"],
    )


@pytest.mark.parametrize(
    ("fixture_path", "build_payload"),
    [
        (
            "tests/fixtures/observer_payloads/helper_pr_comment_trusted_direct_noop.json",
            "trusted_direct",
        ),
        (
            "tests/fixtures/observer_payloads/helper_pr_comment_automation_noop.json",
            "automation_noop",
        ),
    ],
)
def test_python_helper_output_fixtures_match_frozen_helper_contracts(monkeypatch, fixture_path, build_payload):
    fixture = _load_fixture(fixture_path)
    payload = fixture["payload"]
    metadata = fixture["fixture_metadata"]

    harness = CommentRoutingHarness(monkeypatch)
    harness.config.set("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    harness.config.set("COMMENT_BODY", "@guidelines-bot /r? @felix91gr")
    harness.config.set("COMMENT_AUTHOR_ASSOCIATION", "COLLABORATOR")
    harness.config.set("COMMENT_SENDER_TYPE", "User")
    harness.config.set("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    harness.config.set("PR_NUMBER", "42")

    if build_payload == "trusted_direct":
        harness.config.set("COMMENT_USER_TYPE", "User")
        harness.config.set("COMMENT_AUTHOR", "PLeVasseur")
        harness.config.set("COMMENT_INSTALLATION_ID", "")
        harness.config.set("COMMENT_ID", "100")
        harness.config.set("COMMENT_AUTHOR_ID", "123")
        harness.config.set("COMMENT_CREATED_AT", "2026-03-20T20:48:25Z")
        harness.config.set("GITHUB_RUN_ID", "999")
        harness.config.set("GITHUB_RUN_ATTEMPT", "1")
    else:
        harness.config.set("COMMENT_USER_TYPE", "Bot")
        harness.config.set("COMMENT_AUTHOR", "dependabot[bot]")
        harness.config.set("COMMENT_INSTALLATION_ID", "")
        harness.config.set("COMMENT_ID", "101")
        harness.config.set("COMMENT_AUTHOR_ID", "124")
        harness.config.set("COMMENT_CREATED_AT", "2026-03-20T20:49:25Z")
        harness.config.set("GITHUB_RUN_ID", "998")
        harness.config.set("GITHUB_RUN_ATTEMPT", "2")

    harness.github.add_api(
        "GET",
        "pulls/42",
        {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "PLeVasseur"},
        },
    )

    actual = comment_routing.build_pr_comment_observer_payload(harness.runtime, 42)

    assert metadata["contract_class"] == "python_helper_output"
    assert metadata["contract_source"] == "production Python helper"
    assert actual == payload
    assert reconcile_payloads.parse_deferred_context_payload(payload).raw_payload == payload


def test_observer_contract_matrix_separates_workflow_and_helper_sources():
    matrix = _load_contract_matrix()

    assert {item["contract_source"] for item in matrix["workflow_emitted_payloads"]} == {"workflow YAML"}
    assert {item["contract_source"] for item in matrix["python_helper_outputs"]} == {
        "production Python helper"
    }

    workflow_fixture_paths = {item["fixture_path"] for item in matrix["workflow_emitted_payloads"]}
    helper_fixture_paths = {item["fixture_path"] for item in matrix["python_helper_outputs"]}

    assert workflow_fixture_paths.isdisjoint(helper_fixture_paths)

    for fixture_path in workflow_fixture_paths:
        fixture = _load_fixture(fixture_path)
        assert fixture["fixture_metadata"]["contract_class"] == "workflow_emitted_payload"
        assert fixture["payload"].get("kind") != "observer_noop"

    for fixture_path in helper_fixture_paths:
        fixture = _load_fixture(fixture_path)
        assert fixture["fixture_metadata"]["contract_class"] == "python_helper_output"
        assert fixture["payload"]["kind"] == "observer_noop"
