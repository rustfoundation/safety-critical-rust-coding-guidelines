from pathlib import Path
import pytest

pytestmark = pytest.mark.contract

import yaml

def test_sweeper_repair_workflow_exposes_reviewer_board_preview_dispatch():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8"))
    on_block = data.get("on", data.get(True))
    workflow_dispatch = on_block["workflow_dispatch"]
    action_input = workflow_dispatch["inputs"]["action"]
    assert "preview-reviewer-board" in action_input["options"]
    issue_number_input = workflow_dispatch["inputs"]["issue_number"]
    assert issue_number_input["required"] is False
    assert issue_number_input["type"] == "string"

def test_sweeper_repair_workflow_scopes_reviewer_board_env_to_preview_only():
    workflow_text = Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8")
    assert "ISSUE_NUMBER: ${{ github.event.inputs.issue_number }}" in workflow_text
    assert (
        "REVIEWER_BOARD_ENABLED: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && 'true' || 'false' }}"
        in workflow_text
    )
    assert (
        "REVIEWER_BOARD_TOKEN: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && secrets.REVIEWER_BOARD_TOKEN || '' }}"
        in workflow_text
    )
