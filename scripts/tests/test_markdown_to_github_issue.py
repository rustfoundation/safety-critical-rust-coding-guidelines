from pathlib import Path

import pytest

from .. import markdown_to_github_issue as mtgi  # noqa: TID252

DATA_DIR = Path("scripts/tests/data")


@pytest.mark.parametrize(
    ["file", "expected"],
    [
        ("empty_table", None),
        (
            "table_with_single_line",
            [
                mtgi.MISRA_Rule(
                    section="D.1.2",
                    title="The use of language extensions should be minimized",
                    status="Advisory",
                    rationale="IDB",
                    applicability="Yes Yes",
                    category="Required",
                ),
            ],
        ),
        (
            "table_with_multiple_lines",
            [
                mtgi.MISRA_Rule(
                    section="D.1.2",
                    title="The use of language extensions should be minimized",
                    status="Advisory",
                    rationale="IDB",
                    applicability="Yes Yes",
                    category="Required",
                ),
                mtgi.MISRA_Rule(
                    section="R.1.3",
                    title="There shall be no occurrence of undefined or critical unspecified behaviour",
                    status="Required",
                    decidability="Undecidable",
                    scope="System",
                    rationale="UB, IDB",
                    applicability="Yes Yes",
                    category="Required",
                ),
            ],
        ),
    ],
)
def test_misra_md_import(file: str, expected: list[mtgi.MISRA_Rule] | None) -> None:
    result = mtgi.MISRA_Rules.try_from_md(DATA_DIR / f"{file}.md")
    assert result is None or result.rules == expected
