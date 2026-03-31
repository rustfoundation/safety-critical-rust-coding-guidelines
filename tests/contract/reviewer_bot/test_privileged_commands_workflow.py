from pathlib import Path


def test_privileged_commands_workflow_executes_source_entrypoint():
    workflow_text = Path(".github/workflows/reviewer-bot-privileged-commands.yml").read_text(
        encoding="utf-8"
    )
    assert "Fetch trusted bot source tarball" in workflow_text
    assert 'REVIEWER_BOT_TARGET_REPO_ROOT: ${{ github.workspace }}' in workflow_text
    assert (
        'run: uv run --project "$BOT_SRC_ROOT" python "$BOT_SRC_ROOT/scripts/reviewer_bot.py"'
        in workflow_text
    )
