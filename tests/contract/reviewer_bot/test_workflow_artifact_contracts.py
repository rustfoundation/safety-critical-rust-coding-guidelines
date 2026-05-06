import io
import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

pytestmark = pytest.mark.contract

from scripts.reviewer_bot_lib import reconcile_payloads


def _load_fixture_payload(relative_path: str) -> dict:
    data = json.loads(Path(relative_path).read_text(encoding="utf-8"))
    return data["payload"]


def _load_workflow_job(relative_path: str) -> dict:
    workflow = yaml.safe_load(Path(relative_path).read_text(encoding="utf-8"))
    job_name = "route-pr-comment" if relative_path.endswith("reviewer-bot-pr-comment-router.yml") else "observer"
    return workflow["jobs"][job_name]


def _payload_and_upload_steps(job: dict) -> tuple[dict, dict]:
    build_step = next(step for step in job["steps"] if step.get("env", {}).get("PAYLOAD_PATH", "").endswith(".json"))
    upload_step = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    return build_step, upload_step


def _extract_python_heredoc(run_script: str) -> str:
    lines = run_script.splitlines()
    for index, line in enumerate(lines):
        if line.rstrip().endswith("python - <<'PY'"):
            body_lines = lines[index + 1 :]
            break
    else:
        raise AssertionError("workflow step does not contain a single-quoted Python heredoc")
    for index, line in enumerate(body_lines):
        if line == "PY":
            return "\n".join(body_lines[:index])
    raise AssertionError("workflow step Python heredoc is not terminated")


def _execute_payload_builder(workflow_path: str, env_values: dict[str, str], monkeypatch) -> dict:
    build_step, _ = _payload_and_upload_steps(_load_workflow_job(workflow_path))
    for name, value in env_values.items():
        monkeypatch.setenv(name, value)

    exec(compile(_extract_python_heredoc(build_step["run"]), workflow_path, "exec"), {})

    return json.loads(Path(env_values["PAYLOAD_PATH"]).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("workflow_path",),
    [
        (".github/workflows/reviewer-bot-pr-comment-router.yml",),
        (".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",),
        (".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",),
        (".github/workflows/reviewer-bot-pr-review-comment-observer.yml",),
    ],
)
def test_observer_workflow_files_upload_exactly_one_json_payload(workflow_path):
    build_step, upload_step = _payload_and_upload_steps(_load_workflow_job(workflow_path))

    assert build_step["env"]["PAYLOAD_PATH"].endswith(".json")
    assert upload_step["with"]["path"] == build_step["env"]["PAYLOAD_PATH"]
    assert isinstance(upload_step["with"]["name"], str) and upload_step["with"]["name"]


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
def test_deferred_payload_fixtures_parse_identity_without_packaging_contracts(
    fixture_path, expected_event_name, expected_event_action
):
    payload = _load_fixture_payload(fixture_path)
    parsed = reconcile_payloads.parse_deferred_context_payload(payload)

    assert parsed.identity.source_event_name == expected_event_name
    assert parsed.identity.source_event_action == expected_event_action
    assert parsed.identity.source_run_id == payload["source_run_id"]
    assert parsed.identity.source_run_attempt == payload["source_run_attempt"]
    assert parsed.raw_payload == payload


def test_deferred_comment_payload_parses_without_artifact_name_field():
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")
    payload.pop("source_artifact_name", None)

    parsed = reconcile_payloads.parse_deferred_context_payload(payload)

    assert parsed.identity.source_event_name == "issue_comment"


def test_pr_comment_router_workflow_payload_builder_emits_parseable_contract(monkeypatch, tmp_path):
    workflow_path = ".github/workflows/reviewer-bot-pr-comment-router.yml"
    payload_path = tmp_path / "deferred-comment.json"
    event_path = tmp_path / "event.json"
    output_path = tmp_path / "github-output.txt"
    event_path.write_text(
        json.dumps(
            {
                "issue": {
                    "number": 42,
                    "state": "open",
                    "user": {"login": "dana"},
                    "labels": [{"name": "triage"}],
                },
                "comment": {
                    "id": 501,
                    "body": "hello\n@guidelines-bot /queue",
                    "created_at": "2026-03-20T20:48:25Z",
                    "user": {"login": "contributor", "id": 7001, "type": "User"},
                    "author_association": "CONTRIBUTOR",
                    "performed_via_github_app": None,
                },
                "sender": {"type": "User"},
                "installation": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request: io.StringIO(
            json.dumps(
                {
                    "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
                    "user": {"login": "dana"},
                }
            )
        ),
    )

    payload = _execute_payload_builder(
        workflow_path,
        {
            "PAYLOAD_PATH": str(payload_path),
            "GITHUB_EVENT_PATH": str(event_path),
            "GITHUB_OUTPUT": str(output_path),
            "GITHUB_REPOSITORY": "rustfoundation/safety-critical-rust-coding-guidelines",
            "GITHUB_RUN_ID": "401",
            "GITHUB_RUN_ATTEMPT": "3",
            "GITHUB_TOKEN": "token",
        },
        monkeypatch,
    )

    fixture_payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json")

    assert payload == fixture_payload
    assert reconcile_payloads.parse_deferred_context_payload(payload).identity.source_event_key == "issue_comment:501"


@pytest.mark.parametrize(
    ("workflow_path", "fixture_path", "env_values"),
    [
        (
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
            {
                "GITHUB_RUN_ID": "402",
                "GITHUB_RUN_ATTEMPT": "4",
                "PR_NUMBER": "42",
                "REVIEW_ID": "601",
                "SUBMITTED_AT": "2026-03-20T20:50:00Z",
                "REVIEW_STATE": "approved",
                "COMMIT_ID": "abc123def456",
                "REVIEW_AUTHOR": "reviewer1",
                "REVIEW_AUTHOR_ID": "7002",
            },
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
            {
                "GITHUB_RUN_ID": "403",
                "GITHUB_RUN_ATTEMPT": "5",
                "PR_NUMBER": "42",
                "REVIEW_ID": "602",
                "SOURCE_DISMISSED_AT": "2026-03-17T10:15:00Z",
                "COMMIT_ID": "fedcba654321",
                "REVIEW_AUTHOR": "maintainer1",
                "REVIEW_AUTHOR_ID": "7003",
            },
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
            {
                "GITHUB_RUN_ID": "404",
                "GITHUB_RUN_ATTEMPT": "6",
                "COMMENT_BODY": "@guidelines-bot /queue",
                "PR_NUMBER": "42",
                "ISSUE_AUTHOR": "dana",
                "ISSUE_STATE": "open",
                "ISSUE_LABELS": '["coding guideline"]',
                "COMMENT_ID": "701",
                "COMMENT_CREATED_AT": "2026-03-20T21:00:00Z",
                "COMMENT_AUTHOR": "reviewer2",
                "COMMENT_AUTHOR_ID": "7004",
                "COMMENT_USER_TYPE": "User",
                "COMMENT_COMMIT_ID": "abc123def456",
                "COMMENT_SENDER_TYPE": "User",
                "COMMENT_INSTALLATION_ID": "",
                "COMMENT_PERFORMED_VIA_GITHUB_APP": "false",
            },
        ),
    ],
)
def test_observer_workflow_payload_builders_emit_parseable_contracts(
    workflow_path,
    fixture_path,
    env_values,
    monkeypatch,
    tmp_path,
):
    payload_path = tmp_path / Path(_payload_and_upload_steps(_load_workflow_job(workflow_path))[0]["env"]["PAYLOAD_PATH"]).name
    payload = _execute_payload_builder(
        workflow_path,
        {"PAYLOAD_PATH": str(payload_path), **env_values},
        monkeypatch,
    )
    parsed = reconcile_payloads.parse_deferred_context_payload(payload)
    fixture_payload = _load_fixture_payload(fixture_path)

    assert payload == fixture_payload
    assert parsed.raw_payload == fixture_payload


def test_dismissed_review_payload_carries_source_dismissal_time_contract():
    payload = _load_fixture_payload("tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json")
    matrix = json.loads(Path("tests/fixtures/workflow_contracts/observer_payload_contract_matrix.json").read_text(encoding="utf-8"))
    contract = next(item for item in matrix["payload_contracts"] if item["payload_kind"] == "deferred_review_dismissed")

    assert "source_dismissed_at" in contract["carried_edge_fields"]
    assert payload["source_dismissed_at"] == "2026-03-17T10:15:00Z"


@pytest.mark.parametrize(
    ("fixture_path", "workflow_path"),
    [
        (
            "tests/fixtures/observer_payloads/workflow_pr_comment_deferred.json",
            ".github/workflows/reviewer-bot-pr-comment-router.yml",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_submitted_deferred.json",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_dismissed_deferred.json",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
        ),
        (
            "tests/fixtures/observer_payloads/workflow_pr_review_comment_deferred.json",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
        ),
    ],
)
def test_deferred_payload_fixtures_do_not_require_exact_artifact_name_helpers(
    fixture_path, workflow_path
):
    payload = _load_fixture_payload(fixture_path)
    job = _load_workflow_job(workflow_path)
    build_step, upload_step = _payload_and_upload_steps(job)

    payload_without_artifact_name = dict(payload)
    payload_without_artifact_name.pop("source_artifact_name", None)

    parsed = reconcile_payloads.parse_deferred_context_payload(payload_without_artifact_name)

    assert parsed.identity.source_run_id == payload["source_run_id"]
    assert parsed.identity.source_run_attempt == payload["source_run_attempt"]
    assert isinstance(upload_step["with"]["name"], str) and upload_step["with"]["name"]
    assert build_step["env"]["PAYLOAD_PATH"].endswith(".json")
    assert upload_step["with"]["path"].endswith(".json")


def test_validate_workflow_run_artifact_identity_rejects_run_attempt_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "payload_kind": "deferred_comment",
        "schema_version": 3,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Router",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    bot = SimpleNamespace(get_config_value=lambda name, default="": __import__("os").environ.get(name, default))

    with pytest.raises(RuntimeError, match="run_attempt mismatch"):
        reconcile_payloads.validate_workflow_run_artifact_identity(bot, payload)


def test_validate_workflow_run_artifact_identity_requires_successful_conclusion(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "failure")
    payload = {
        "payload_kind": "deferred_comment",
        "schema_version": 3,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Router",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    bot = SimpleNamespace(get_config_value=lambda name, default="": __import__("os").environ.get(name, default))

    with pytest.raises(RuntimeError, match="did not conclude successfully"):
        reconcile_payloads.validate_workflow_run_artifact_identity(bot, payload)
