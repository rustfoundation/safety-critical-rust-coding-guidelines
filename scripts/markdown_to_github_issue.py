#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import bs4
import markdown
from github import Auth, Github

EXPECTED_HEADINGS: Final[list[str]] = [
    "Guideline",
    "Guideline Name",
    "MISRA C:2025 Status",
    "Decidability",
    "Scope",
    "Rationale",
    "Applicability",
    "Adjusted Category",
]


@dataclass(eq=True)
class MISRA_Rule:
    title: str
    section: str | None = None
    status: str | None = None
    decidability: str | None = None
    scope: str | None = None
    rationale: str | None = None
    applicability: str | None = None
    category: str | None = None

    @classmethod
    def from_cols(cls, cols: list[str | None]) -> MISRA_Rule | None:
        assert len(cols) == len(EXPECTED_HEADINGS), (
            f"Expected {len(EXPECTED_HEADINGS)}, got {len(cols)}"
        )
        # Cannot create rule without a title
        title = cols[EXPECTED_HEADINGS.index("Guideline Name")]
        if title is None:
            return None
        return MISRA_Rule(
            title=title,
            section=cols[EXPECTED_HEADINGS.index("Guideline")],
            status=cols[EXPECTED_HEADINGS.index("MISRA C:2025 Status")],
            decidability=cols[EXPECTED_HEADINGS.index("Decidability")],
            scope=cols[EXPECTED_HEADINGS.index("Scope")],
            rationale=cols[EXPECTED_HEADINGS.index("Rationale")],
            applicability=cols[EXPECTED_HEADINGS.index("Applicability")],
            category=cols[EXPECTED_HEADINGS.index("Adjusted Category")],
        )

    @property
    def issue_body(self) -> str:
        # FIXME(senier): Properly layout (we could even use .github/ISSUE_TEMPLATE/CODING-GUILDELINE.yml to validate the format)
        # FIXME(senier): Transform into dedicated coding guidline object and do layouting there
        return str(self)


def convert_md(file: Path) -> list[MISRA_Rule] | None:
    result = None

    with file.open() as f:
        html = markdown.markdown(f.read(), extensions=["tables"], output_format="xhtml")
        soup = bs4.BeautifulSoup(html, features="lxml")

        table = soup.find("table")
        if table is None or not isinstance(table, bs4.Tag):
            return None

        headings = table.find("thead")
        if headings is None or not isinstance(headings, bs4.Tag):
            return None

        values = [h.text for h in headings.find_all("th")]
        if values != EXPECTED_HEADINGS:
            return None

        body = table.find("tbody")
        if body is None or not isinstance(body, bs4.Tag):
            return None

        for row in body.find_all("tr"):
            if row is None or not isinstance(row, bs4.Tag):
                continue

            cols = [r.text or None for r in row.find_all("td")]
            assert len(cols) == 0 or len(cols) == len(EXPECTED_HEADINGS), f"{cols}"

            # skip empty rows
            if all(c is None for c in cols):
                continue

            if result is None:
                result = []
            rule = MISRA_Rule.from_cols(cols)
            if rule is not None:
                result.append(rule)
    return result


def create_issues(repo_name: str, token: str, rules: list[MISRA_Rule]):
    auth = Auth.Token(token=token)
    github = Github(auth=auth)
    repo = github.get_repo(repo_name)

    for rule in rules:
        if rule.title is None:
            continue
        repo.create_issue(title=rule.title, body=rule.issue_body)


def import_rules(file: Path, repo: str, token: str) -> int | str:
    md = convert_md(file)
    if md is None:
        return "No rules found"
    create_issues(repo_name=repo, token=token, rules=md)
    return 1


def main() -> int | str:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m",
        "--markdown",
        type=Path,
        required=True,
        help="Markdown file to extract rules from",
    )
    parser.add_argument(
        "-r",
        "--repository",
        type=str,
        required=True,
        help="Github repository to import rules to (format: account/repository)",
    )
    parser.add_argument(
        "-a",
        "--auth-token",
        type=str,
        required=True,
        help="Github authentication token",
    )
    args = parser.parse_args()
    return import_rules(file=args.markdown, repo=args.repository, token=args.auth_token)


if __name__ == "__main__":
    main()
