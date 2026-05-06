from pathlib import Path

import pytest

pytestmark = pytest.mark.contract


def _shipped_behavior_files() -> list[Path]:
    roots = [Path("scripts/reviewer_bot_core"), Path("scripts/reviewer_bot_lib"), Path(".github/workflows")]
    files: list[Path] = []
    for root in roots:
        files.extend(path for path in root.rglob("*") if path.is_file() and path.suffix in {".py", ".yml", ".yaml"})
    files.extend(path for path in Path("docs").glob("reviewer-bot-*.md") if path.is_file())
    return sorted(files)


def test_shipped_reviewer_bot_behavior_does_not_depend_on_opencode_tooling():
    forbidden = ("OPENCODE_", "OPENCODE_CONFIG_DIR", "opencode-project-agents")
    offenders: list[str] = []
    for path in _shipped_behavior_files():
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            offenders.append(str(path))

    assert offenders == []
