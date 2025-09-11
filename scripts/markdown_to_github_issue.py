#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

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

    def try_to_rule(self) -> Rule | None:
        category = Category.try_from_misra(self.category)

        if self.title[0].isdigit():
            print(f"Skipping bogus section title entry [{self.title}]", file=sys.stderr)
            return None

        if "Renumbered as" in self.title or "Combined with" in self.title:
            print(f"Skipping renumbered/combined entry [{self.title}]", file=sys.stderr)
            return None

        if category is not None and category.value == "disapplied":
            print(f"Skipping disapplied MISRA rule [{self.section}]", file=sys.stderr)
            return None

        # Clean up title
        title = self.title
        match = re.match(r"^(Dir|Rule) \d+\.\d+(?P<title>[^d].*)", title)
        if match:
            title = match["title"]

        return Rule(
            title=title,
            issue=None,
            chapter=Chapter.try_from_misra_rule(self.section),
            category=category,
            decidability=Decidability.try_from_misra(self.decidability),
            scope=Scope.try_from_misra(self.scope),
            status=Status(value="draft"),
            extra={
                "MISRA Rule Information": [
                    f"Source section: {self.section}",
                    f"Rationale: {self.rationale}",
                ]
            },
        )
        return None


class MISRA_Rules:
    def __init__(self, rules: list[MISRA_Rule]):
        self.rules = rules

    @staticmethod
    def try_from_md(file: Path) -> MISRA_Rules | None:
        result: list[MISRA_Rule] | None = None

        with file.open() as f:
            html = markdown.markdown(
                f.read(), extensions=["tables"], output_format="xhtml"
            )
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

        if not result:
            return None
        return MISRA_Rules(rules=result)

    def create_issues(self, repo_name: str, token: str):
        print(f"Importing into {repo_name}", file=sys.stderr)
        auth = Auth.Token(token=token)
        github = Github(auth=auth)
        repo = github.get_repo(repo_name)

        for misra_rule in self.rules:
            rule = misra_rule.try_to_rule()
            if rule is None:
                continue
            print(f"Importing [{rule.title}]", file=sys.stderr)
            repo.create_issue(
                title=rule.title,
                labels=rule.issue_labels,
                body=rule.body or "",
            )


def get_label(category: str, labels: list[str]) -> str | None:
    for label in labels:
        components = list(map(str.strip, label.split(":")))
        if len(components) != 2:
            continue
        label_cat, value = components
        if category == label_cat:
            return value
    return None


ScopeValues = Literal["module"] | Literal["system"] | Literal["crate"]


@dataclass(eq=True)
class Scope:
    value: ScopeValues

    @classmethod
    def try_from_labels(cls, labels: list[str]) -> Scope | None:
        value = get_label("scope", labels)
        if value == "module" or value == "system" or value == "crate":
            return Scope(value=value)
        return None

    @property
    def label(self) -> str:
        return f"scope: {self.value}"

    @classmethod
    def try_from_misra(cls, value: str | None) -> Scope | None:
        if value is None:
            return None
        normalized = value.lower()
        if normalized == "system":
            return Scope(value="system")
        elif normalized == "STU":
            # FIXME(senier): I mapping STU -> crate correct?
            return Scope(value="crate")
        return None


StatusValues = Literal["draft"] | Literal["approved"] | Literal["retired"]


@dataclass(eq=True)
class Status:
    value: StatusValues

    @classmethod
    def try_from_labels(cls, labels: list[str]) -> Status | None:
        value = get_label("status", labels)
        if value == "draft" or value == "approved" or value == "retired":
            return Status(value=value)
        return None

    @property
    def label(self) -> str:
        return f"status: {self.value}"


CategoryValues = (
    Literal["advisory"]
    | Literal["disapplied"]
    | Literal["mandatory"]
    | Literal["required"]
)


@dataclass(eq=True)
class Category:
    value: CategoryValues

    @classmethod
    def try_from_labels(cls, labels: list[str]) -> Category | None:
        value = get_label("category", labels)
        if (
            value == "advisory"
            or value == "disapplied"
            or value == "mandatory"
            or value == "required"
        ):
            return Category(value=value)
        return None

    @classmethod
    def try_from_misra(cls, value: str | None) -> Category | None:
        if value is None:
            return None
        normalized = value.lower()
        if (
            normalized == "advisory"
            or normalized == "mandatory"
            or normalized == "required"
            or normalized == "disapplied"
        ):
            return Category(value=normalized)
        # FIXME(senier): Mapping "Recommended" to Advisory - is this correct?
        if normalized == "recommended":
            return Category(value="advisory")
        return None

    @property
    def label(self) -> str:
        return f"category: {self.value}"


ChapterValues = (
    Literal["patterns"]
    | Literal["attributes"]
    | Literal["concurrency"]
    | Literal["expressions"]
    | Literal["ffi"]
    | Literal["functions"]
    | Literal["generics"]
    | Literal["implementations"]
    | Literal["macros"]
    | Literal["statements"]
    | Literal["unsafety"]
    | Literal["values"]
    | Literal["associated-items"]
    | Literal["inline-assembly"]
    | Literal["entities-and-resolution"]
    | Literal["exceptions-and-errors"]
    | Literal["ownership-and-destruction"]
    | Literal["types-and-traits"]
    | Literal["program-structure-and-compilation"]
)

MISRA_MAPPING: dict[tuple[Literal["R", "D"], int], ChapterValues | None] = {
    ("D", 1): None,  # The implementation
    ("D", 2): "program-structure-and-compilation",  # Compilation and build
    ("D", 3): None,  # Requirements traceability
    ("D", 4): None,  # Code design
    ("D", 5): "concurrency",  # Concurrency considerations
    ("R", 1): None,  # A standard C environment
    ("R", 2): None,  # Unused code
    ("R", 3): None,  # Comments
    ("R", 4): None,  # Character sets and lexical elements
    ("R", 5): "entities-and-resolution",  # Identifiers
    ("R", 6): "types-and-traits",  # Types
    ("R", 7): "values",  # Literals and constants
    ("R", 8): "values",  # Declarations and definitions
    ("R", 9): "values",  # Initialization
    ("R", 10): "types-and-traits",  # The essential type model
    ("R", 11): "types-and-traits",  # Pointer type conversions
    ("R", 12): "expressions",  # Expressions
    ("R", 13): None,  # Side effects
    ("R", 14): "expressions",  # Control statement expressions
    ("R", 15): "expressions",  # Control flow
    ("R", 16): "patterns",  # Switch statements
    ("R", 17): "functions",  # Functions
    ("R", 18): "types-and-traits",  # Pointers and arrays
    ("R", 19): None,  # Overlapping storage
    ("R", 20): "macros",  # Preprocessing directives
    ("R", 21): None,  # Standard libraries
    ("R", 22): "ownership-and-destruction",  # Resources
    ("R", 23): "generics",  # Generic selections
}


@dataclass(eq=True)
class Chapter:
    value: ChapterValues

    @classmethod
    def try_from_labels(cls, labels: list[str]) -> Chapter | None:
        value = get_label("chapter", labels)
        if (
            value == "associated-items"
            or value == "attributes"
            or value == "concurrency"
            or value == "entities-and-resolution"
            or value == "exceptions-and-errors"
            or value == "expressions"
            or value == "ffi"
            or value == "functions"
            or value == "generics"
            or value == "implementations"
            or value == "inline-assembly"
            or value == "macros"
            or value == "ownership-and-destruction"
            or value == "patterns"
            or value == "program-structure-and-compilation"
            or value == "statements"
            or value == "types-and-traits"
            or value == "unsafety"
            or value == "values"
        ):
            return Chapter(value=value)
        return None

    @classmethod
    def try_from_misra_rule(cls, rule_name: str | None) -> Chapter | None:
        if rule_name is None:
            return None

        match = re.match(
            r"^\s*(?P<kind>[DR])\.(?P<category>[0-9]+)\.[0-9]+\s*$", rule_name
        )
        if match is None:
            return None

        category = int(match["category"])
        kind = match["kind"]
        assert kind == "D" or kind == "R"

        if (kind, category) not in MISRA_MAPPING:
            return None

        mapped_category = MISRA_MAPPING[(kind, category)]
        if mapped_category is None:
            return None

        return Chapter(mapped_category)

    @property
    def label(self) -> str:
        return f"chapter: {self.value}"

    @property
    def title(self) -> str:
        if self.value == "ffi":
            return "FFI"
        return " ".join([str(v.title()) for v in self.value.split("-")])


@dataclass(eq=True)
class Decidability:
    is_decidable: bool

    @classmethod
    def try_from_labels(cls, labels: list[str]) -> Decidability | None:
        value = get_label("decidability", labels)
        if value == "decidable":
            return Decidability(True)
        elif value == "undecidable":
            return Decidability(False)
        return None

    @property
    def label(self) -> str:
        return f"decidability: {'decidable' if self.value else 'undecidable'}"

    @property
    def value(self) -> str:
        return "decidable" if self.is_decidable else "undecidable"

    @classmethod
    def try_from_misra(cls, value: str | None) -> Decidability | None:
        if value is None:
            return None
        normalized = value.lower()
        if normalized == "decidable" or normalized == "undecidable":
            return Decidability(is_decidable=(normalized == "decidable"))
        return None


@dataclass(eq=True)
class Rule:
    title: str
    issue: int | None
    category: Category | None = None
    chapter: Chapter | None = None
    decidability: Decidability | None = None
    scope: Scope | None = None
    status: Status | None = None
    extra: dict[str, list[str]] | None = None

    @classmethod
    def try_from_issue(cls, issue: int, title: str, labels: list[str]) -> Rule | None:
        if "coding guideline" not in labels and "[Coding Guideline]" not in title:
            return None

        category = Category.try_from_labels(labels)
        chapter = Chapter.try_from_labels(labels)
        decidability = Decidability.try_from_labels(labels)
        scope = Scope.try_from_labels(labels)
        status = Status.try_from_labels(labels)

        return Rule(
            title=title,
            issue=issue,
            category=category,
            chapter=chapter,
            decidability=decidability,
            scope=scope,
            status=status,
        )

    @property
    def issue_labels(self) -> list[str]:
        return [
            e.label
            for e in [
                self.category,
                self.chapter,
                self.decidability,
                self.scope,
                self.status,
            ]
            if e is not None
        ] + ["coding guideline"]

    @property
    def fields(self) -> dict[str, str]:
        return {
            "Title": self.title,
            "Issue": f"#{self.issue}" if self.issue else "",
            "Category": self.category.value if self.category else "",
            "Chapter": self.chapter.value if self.chapter else "",
            "Decidability": self.decidability.value if self.decidability else "",
            "Scope": self.scope.value if self.scope else "",
            "Status": self.status.value if self.status else "",
            "Extra": "; ".join(f"{k}: {', '.join(v)}" for k, v in self.extra.items())
            if self.extra
            else "",
        }

    @property
    def body(self) -> str | None:
        if self.extra is None:
            return None
        return "\n".join(
            [
                f"# {title}\n\n{'\n'.join(content)}"
                for title, content in self.extra.items()
            ]
        )


class Rules:
    def __init__(self, rules: list[Rule]):
        self.rules = rules

    @staticmethod
    def try_from_repo(repo_name: str, token: str) -> Rules | None:
        auth = Auth.Token(token=token)
        github = Github(auth=auth)
        repo = github.get_repo(repo_name)

        issues = list(repo.get_issues(state="all"))

        result: list[Rule] | None = []
        for index, issue in enumerate(issues):
            if issue.pull_request is not None:
                continue
            print(f"Importing issue #{issue.number}", file=sys.stderr)
            rule = Rule.try_from_issue(
                issue.number, issue.title, [label.name for label in issue.get_labels()]
            )
            if rule is not None:
                result.append(rule)

        if not result:
            return None
        return Rules(rules=result)

    @staticmethod
    def try_from_misra(misra_rules: MISRA_Rules) -> Rules | None:
        result = [r for mr in misra_rules.rules if (r := mr.try_to_rule()) is not None]
        if not result:
            return None
        return Rules(rules=result)

    def to_markdown(
        self,
        file: Path,
        title: str | None = None,
        show_issue_number: bool | None = None,
        show_extra_data: bool | None = None,
    ):
        print(f"Converting to {file}\n", file=sys.stderr)

        grouped_rules = {}
        for rule in self.rules:
            chapter = (
                "No chapter assigned" if rule.chapter is None else rule.chapter.title
            )
            if chapter not in grouped_rules:
                grouped_rules[chapter] = []
            grouped_rules[chapter].append(rule)

        with file.open("w") as f:
            f.write(f"# {title or 'Rules'}\n")

            for chapter, rules in grouped_rules.items():
                f.write(f"\n## {chapter}\n\n")

                for index, rule in enumerate(rules):
                    fields = {}
                    for name, field in rule.fields.items():
                        if name == "Title" and show_issue_number:
                            continue
                        if name == "Issue" and not show_issue_number:
                            continue
                        if name == "Extra" and not show_extra_data:
                            continue
                        fields[name] = field

                    if index == 0:
                        f.write("| " + " | ".join(fields.keys()) + " |\n")
                        f.write(
                            "| " + " | ".join("---" for _ in fields.keys()) + " |\n"
                        )
                    f.write("| " + " | ".join(fields.values()) + " |\n")


def import_misra_rules(args: argparse.Namespace) -> int | str:
    misra_rules = MISRA_Rules.try_from_md(args.markdown)
    if misra_rules is None:
        return "No rules found"
    misra_rules.create_issues(repo_name=args.repository, token=args.auth_token)
    return 1


def export_issues_to_md(args: argparse.Namespace) -> int | str:
    rules = Rules.try_from_repo(repo_name=args.repository, token=args.auth_token)
    if rules is None:
        return f"No rules found in repository {args.repository}"
    rules.to_markdown(
        file=args.markdown,
        title=args.title,
        show_issue_number=True,
        show_extra_data=False,
    )
    return 0


def convert_misra_to_rules(args: argparse.Namespace) -> int | str:
    misra_rules = MISRA_Rules.try_from_md(args.markdown)
    if misra_rules is None:
        return "No rules found"
    rules = Rules.try_from_misra(misra_rules)
    if rules is None:
        return "No rules converted"
    rules.to_markdown(file=args.output, title=args.title, show_issue_number=False)
    return 0


def main() -> int | str:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-m",
        "--markdown",
        type=Path,
        required=True,
        help="Markdown file to extract rules from",
    )

    subparsers = parser.add_subparsers(dest="subcommand")

    parser_misra_to_issues = subparsers.add_parser(
        "misra_import", help="import MISRA markdown to issues"
    )
    parser_misra_to_issues.add_argument(
        "-r",
        "--repository",
        type=str,
        required=True,
        help="Github repository to import rules to (format: account/repository)",
    )
    parser_misra_to_issues.add_argument(
        "-a",
        "--auth-token",
        type=str,
        required=True,
        help="Github authentication token",
    )
    parser_misra_to_issues.set_defaults(func=import_misra_rules)

    parser_issues_to_md = subparsers.add_parser(
        "issues_export", help="export issues to markdown"
    )
    parser_issues_to_md.add_argument(
        "-r",
        "--repository",
        type=str,
        required=True,
        help="Github repository to import rules to (format: account/repository)",
    )
    parser_issues_to_md.add_argument(
        "-a",
        "--auth-token",
        type=str,
        required=True,
        help="Github authentication token",
    )
    parser_issues_to_md.add_argument(
        "-t",
        "--title",
        type=str,
        help="Title of markdown document",
    )
    parser_issues_to_md.set_defaults(func=export_issues_to_md)

    parser_misra_to_rules_md = subparsers.add_parser(
        "misra_convert", help="convert MISRA markdown to rules markdown"
    )
    parser_misra_to_rules_md.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Markdown file to create",
    )
    parser_misra_to_rules_md.add_argument(
        "-t",
        "--title",
        type=str,
        help="Title of markdown document",
    )
    parser_misra_to_rules_md.set_defaults(func=convert_misra_to_rules)

    args = parser.parse_args()

    if not args.subcommand:
        parser.print_usage()
        return 2

    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
