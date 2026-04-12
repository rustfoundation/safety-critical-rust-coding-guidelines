from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

def test_privileged_commands_workflow_executes_source_entrypoint():
    workflow_text = Path(".github/workflows/reviewer-bot-privileged-commands.yml").read_text(
        encoding="utf-8"
    )
    assert "Fetch trusted bot source tarball" in workflow_text
    assert 'python "$BOT_SRC_ROOT/scripts/reviewer_bot.py"' in workflow_text


def test_privileged_commands_workflow_stays_isolated_from_observer_and_reconcile_contracts():
    workflow_text = Path(".github/workflows/reviewer-bot-privileged-commands.yml").read_text(
        encoding="utf-8"
    )

    assert "name: Reviewer Bot Privileged Commands" in workflow_text
    assert "workflow_dispatch:" in workflow_text
    assert "source_event_key:" in workflow_text
    assert "reviewer-bot-pr-comment-observer.yml" not in workflow_text
    assert "reviewer-bot-pr-review-submitted-observer.yml" not in workflow_text
    assert "reviewer-bot-pr-review-dismissed-observer.yml" not in workflow_text
    assert "reviewer-bot-pr-review-comment-observer.yml" not in workflow_text
    assert "reviewer-bot-reconcile.yml" not in workflow_text
