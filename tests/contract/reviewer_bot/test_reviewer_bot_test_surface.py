from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.contract


def test_reviewer_bot_tests_cover_core_policy_paths():
    workflow = yaml.safe_load(Path(".github/workflows/reviewer-bot-tests.yml").read_text(encoding="utf-8"))
    on_block = workflow.get("on", workflow.get(True))

    assert "scripts/reviewer_bot_core/**" in on_block["push"]["paths"]
    assert "scripts/reviewer_bot_core/**" in on_block["pull_request"]["paths"]


def test_reviewer_bot_coverage_includes_core_package():
    workflow_text = Path(".github/workflows/reviewer-bot-tests.yml").read_text(encoding="utf-8")

    assert "--cov=scripts.reviewer_bot_core" in workflow_text
    assert "--cov=scripts.reviewer_bot_lib" in workflow_text
