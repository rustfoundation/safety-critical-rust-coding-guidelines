import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

DEFAULT_LABEL = "fls-audit"
DEFAULT_TITLE_PREFIX = "FLS audit:"
DEFAULT_LABEL_COLOR = "0e8a16"


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def github_request(method: str, endpoint: str, data: dict | None = None, params: dict | None = None) -> requests.Response:
    token = require_env("GITHUB_TOKEN")
    owner = require_env("REPO_OWNER")
    repo = require_env("REPO_NAME")
    url = f"https://api.github.com/repos/{owner}/{repo}/{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return requests.request(method, url, headers=headers, json=data, params=params, timeout=30)


def response_json(response: requests.Response) -> object:
    if not response.content:
        return {}
    return response.json()


def ensure_label(label: str) -> None:
    response = github_request("GET", f"labels/{label}")
    if response.status_code == 200:
        return
    if response.status_code != 404:
        print(f"Failed to check label {label}: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)
    create = github_request(
        "POST",
        "labels",
        data={
            "name": label,
            "color": DEFAULT_LABEL_COLOR,
            "description": "FLS audit results",
        },
    )
    if create.status_code >= 400:
        print(f"Failed to create label {label}: {create.status_code} {create.text}", file=sys.stderr)
        sys.exit(1)


def find_open_audit_issue(label: str, title_prefix: str) -> dict | None:
    response = github_request(
        "GET",
        "issues",
        params={"state": "open", "labels": label, "per_page": "100"},
    )
    if response.status_code >= 400:
        print(f"Failed to list issues: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)
    issues = response_json(response)
    if not isinstance(issues, list):
        return None
    filtered = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        if "pull_request" in issue:
            continue
        title = issue.get("title", "")
        if title_prefix and not title.startswith(title_prefix):
            continue
        filtered.append(issue)
    if not filtered:
        return None
    filtered.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return filtered[0]


def has_changes(report: dict) -> bool:
    summary = report.get("summary", {})
    keys = [
        "added",
        "removed",
        "content_changed",
        "renumbered_only",
        "header_changed",
        "section_reordered",
        "section_changed",
    ]
    for key in keys:
        try:
            if int(summary.get(key, 0)) > 0:
                return True
        except (TypeError, ValueError):
            if summary.get(key):
                return True
    return False


def format_title(prefix: str) -> str:
    date_stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"{prefix} changes detected ({date_stamp})"


def build_instructions(report: dict) -> str:
    generated_at = report.get("metadata", {}).get("generated_at")
    if not generated_at:
        generated_at = datetime.now(timezone.utc).isoformat()
    run_url = None
    server_url = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if server_url and repo and run_id:
        run_url = f"{server_url}/{repo}/actions/runs/{run_id}"
    lines = [
        "## What to do",
        "- Review the report below, especially **Affected Guidelines** and **Content Changes**.",
        "- If you believe no guideline updates are required, comment `@guidelines-bot /accept-no-fls-changes` (triage+ only).",
        "- If guideline updates are required, open a PR with the necessary changes and reference this issue.",
        "- Optional: rerun locally for diffs: `uv run python scripts/fls_audit.py --print-diffs`.",
        "- See `docs/fls-audit.md` for the full audit workflow.",
        "",
        "## Audit run",
        f"- Generated at: `{generated_at}`",
    ]
    if run_url:
        lines.append(f"- Workflow run: {run_url}")
    lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def update_issue(issue_number: int, title: str, body: str) -> None:
    response = github_request(
        "PATCH",
        f"issues/{issue_number}",
        data={"title": title, "body": body},
    )
    if response.status_code >= 400:
        print(f"Failed to update issue #{issue_number}: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)


def create_issue(title: str, body: str, label: str) -> dict:
    response = github_request(
        "POST",
        "issues",
        data={"title": title, "body": body, "labels": [label]},
    )
    if response.status_code >= 400:
        print(f"Failed to create issue: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)
    result = response_json(response)
    if isinstance(result, dict):
        return result
    return {}


def comment_on_issue(issue_number: int, body: str) -> None:
    response = github_request(
        "POST",
        f"issues/{issue_number}/comments",
        data={"body": body},
    )
    if response.status_code >= 400:
        print(f"Failed to comment on issue #{issue_number}: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)


def close_issue(issue_number: int) -> None:
    response = github_request(
        "PATCH",
        f"issues/{issue_number}",
        data={"state": "closed"},
    )
    if response.status_code >= 400:
        print(f"Failed to close issue #{issue_number}: {response.status_code} {response.text}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create or update FLS audit issues.")
    parser.add_argument("--report-json", required=True)
    parser.add_argument("--report-md", required=True)
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--title-prefix", default=DEFAULT_TITLE_PREFIX)
    args = parser.parse_args()

    report_json_path = Path(args.report_json)
    report_md_path = Path(args.report_md)
    if not report_json_path.exists():
        print(f"Missing report JSON at {report_json_path}", file=sys.stderr)
        return 1
    if not report_md_path.exists():
        print(f"Missing report Markdown at {report_md_path}", file=sys.stderr)
        return 1

    report = json.loads(report_json_path.read_text(encoding="utf-8"))
    report_md = report_md_path.read_text(encoding="utf-8")
    changes_found = has_changes(report)

    ensure_label(args.label)
    existing_issue = find_open_audit_issue(args.label, args.title_prefix)

    if changes_found:
        title = format_title(args.title_prefix)
        body = build_instructions(report) + report_md
        if existing_issue:
            update_issue(existing_issue["number"], title, body)
            print(f"Updated audit issue #{existing_issue['number']}")
        else:
            created = create_issue(title, body, args.label)
            number = created.get("number")
            if number:
                print(f"Created audit issue #{number}")
            else:
                print("Created audit issue")
        return 0

    if existing_issue:
        generated_at = report.get("metadata", {}).get("generated_at")
        if not generated_at:
            generated_at = datetime.now(timezone.utc).isoformat()
        comment_on_issue(
            existing_issue["number"],
            f"✅ Audit run at `{generated_at}` found no changes. Closing this issue.",
        )
        close_issue(existing_issue["number"])
        print(f"Closed audit issue #{existing_issue['number']}")
    else:
        print("No changes found and no open audit issue to close.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
