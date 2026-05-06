from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract


def _load_preview_workflow() -> tuple[str, dict, dict]:
    text = Path(".github/workflows/reviewer-bot-preview.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    on_block = data.get("on", data.get(True))
    return text, data, on_block


def test_preview_workflow_exposes_exact_dispatch_inputs_and_actions():
    _, data, on_block = _load_preview_workflow()

    assert data["name"] == "Reviewer Bot Preview"
    workflow_dispatch = on_block["workflow_dispatch"]
    assert sorted(workflow_dispatch["inputs"]) == ["action", "issue_number", "validation_nonce"]
    action_input = workflow_dispatch["inputs"]["action"]
    assert action_input["options"] == [
        "preview-check-overdue",
        "preview-status-label-projection",
        "preview-issue314-state-health",
        "preview-reviewer-board",
    ]
    assert workflow_dispatch["inputs"]["issue_number"]["required"] is True
    assert workflow_dispatch["inputs"]["issue_number"]["type"] == "string"
    assert workflow_dispatch["inputs"]["validation_nonce"]["required"] is True
    assert workflow_dispatch["inputs"]["validation_nonce"]["type"] == "string"


def test_preview_workflow_remains_sole_retained_owner_of_preview_actions():
    sweeper_text = Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8")
    sweeper_data = yaml.safe_load(sweeper_text)
    sweeper_on_block = sweeper_data.get("on", sweeper_data.get(True))
    sweeper_action_input = sweeper_on_block["workflow_dispatch"]["inputs"]["action"]

    assert "preview-reviewer-board" not in sweeper_action_input["options"]
    assert "REVIEWER_BOARD_ENABLED" not in sweeper_text
    assert "REVIEWER_BOARD_TOKEN" not in sweeper_text


def test_preview_workflow_run_name_and_env_contract_are_frozen():
    text, data, _ = _load_preview_workflow()

    assert data["run-name"] == "preview ${{ github.event.inputs.action }} issue ${{ github.event.inputs.issue_number }} nonce ${{ github.event.inputs.validation_nonce }}"
    assert "EVENT_NAME: workflow_dispatch" in text
    assert "EVENT_ACTION: ''" in text
    assert "MANUAL_ACTION: ${{ github.event.inputs.action }}" in text
    assert "ISSUE_NUMBER: ${{ github.event.inputs.issue_number }}" in text
    assert "VALIDATION_NONCE: ${{ github.event.inputs.validation_nonce }}" in text
    assert "EVALUATED_REPO: ${{ github.repository }}" in text
    assert "HEAD_SHA: ${{ github.sha }}" in text
    assert "EVALUATED_REF: ${{ github.sha }}" in text
    assert "GITHUB_RUN_ID: ${{ github.run_id }}" in text
    assert "GITHUB_RUN_ATTEMPT: ${{ github.run_attempt }}" in text
    assert "WORKFLOW_RUN_ID: ${{ github.run_id }}" in text
    assert "WORKFLOW_NAME: ${{ github.workflow }}" in text
    assert "WORKFLOW_JOB_NAME: ${{ github.job }}" in text
    assert (
        "REVIEWER_BOARD_ENABLED: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && 'true' || 'false' }}"
        in text
    )
    assert (
        "REVIEWER_BOARD_TOKEN: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && secrets.REVIEWER_BOARD_TOKEN || '' }}"
        in text
    )


def test_preview_workflow_uploads_exact_preview_output_artifact_contract():
    text, data, _ = _load_preview_workflow()

    job = data["jobs"]["reviewer-bot-preview"]
    assert job["permissions"]["contents"] == "read"
    assert job["permissions"]["issues"] == "read"
    assert job["permissions"]["pull-requests"] == "read"
    upload_step = job["steps"][-1]
    assert upload_step["uses"] == "actions/upload-artifact@65462800fd760344b1a7b4382951275a0abb4808"
    assert upload_step["with"]["name"] == "reviewer-bot-preview-output-${{ github.run_id }}-attempt-${{ github.run_attempt }}"
    assert upload_step["with"]["path"] == "${{ runner.temp }}/reviewer-bot-preview-output-${{ github.run_id }}-attempt-${{ github.run_attempt }}"
    assert 'artifact_dir="$RUNNER_TEMP/reviewer-bot-preview-output-${GITHUB_RUN_ID}-attempt-${GITHUB_RUN_ATTEMPT}"' in text
    assert 'uv run --project "$BOT_SRC_ROOT" reviewer-bot > "$artifact_dir/preview-output.json"' in text
