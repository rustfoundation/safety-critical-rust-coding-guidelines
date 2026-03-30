"""GitHub transport and issue/PR mutation helpers."""

import json
import os
import random
import sys
import time
from urllib.parse import quote

import requests

from .config import (
    LOCK_API_RETRY_LIMIT,
    LOCK_RETRY_BASE_SECONDS,
    REVIEWER_BOARD_TOKEN_ENV,
    STATUS_LABEL_CONFIG,
)
from .context import GitHubTransportContext


def get_github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        raise SystemExit(1)
    return token


def get_github_graphql_token(bot: GitHubTransportContext, *, prefer_board_token: bool = False) -> str:
    if prefer_board_token:
        token = os.environ.get(REVIEWER_BOARD_TOKEN_ENV)
        if not token:
            raise RuntimeError(f"{REVIEWER_BOARD_TOKEN_ENV} not set")
        return token
    return bot.get_github_token()


def github_api_request(
    bot: GitHubTransportContext,
    method: str,
    endpoint: str,
    data: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    *,
    suppress_error_log: bool = False,
):
    token = bot.get_github_token()
    repo = f"{os.environ['REPO_OWNER']}/{os.environ['REPO_NAME']}"
    url = f"https://api.github.com/repos/{repo}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if extra_headers:
        headers.update(extra_headers)

    response = requests.request(method, url, headers=headers, json=data)

    payload = None
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = None

    ok = response.status_code < 400
    if not ok and not suppress_error_log:
        print(f"GitHub API error: {response.status_code} - {response.text}", file=sys.stderr)

    normalized_headers = {key.lower(): value for key, value in response.headers.items()}
    return bot.GitHubApiResult(
        status_code=response.status_code,
        payload=payload,
        headers=normalized_headers,
        text=response.text,
        ok=ok,
    )


def github_api(bot: GitHubTransportContext, method: str, endpoint: str, data: dict | None = None):
    response = bot.github_api_request(method, endpoint, data)
    if not response.ok:
        return None
    if response.payload is None:
        return {}
    return response.payload


def github_graphql_request(
    bot: GitHubTransportContext,
    query: str,
    variables: dict | None = None,
    *,
    token: str | None = None,
    suppress_error_log: bool = False,
):
    graphql_token = token or bot.get_github_graphql_token()
    headers = {
        "Authorization": f"Bearer {graphql_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    response = requests.post(
        "https://api.github.com/graphql",
        headers=headers,
        json={"query": query, "variables": variables or {}},
    )

    payload = None
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = None

    graphql_errors = payload.get("errors") if isinstance(payload, dict) else None
    ok = response.status_code < 400 and not graphql_errors
    if not ok and not suppress_error_log:
        details = response.text
        if graphql_errors:
            details = json.dumps(graphql_errors, sort_keys=True)
        print(f"GitHub GraphQL error: {response.status_code} - {details}", file=sys.stderr)

    normalized_headers = {key.lower(): value for key, value in response.headers.items()}
    return bot.GitHubApiResult(
        status_code=response.status_code,
        payload=payload,
        headers=normalized_headers,
        text=response.text,
        ok=ok,
    )


def github_graphql(
    bot: GitHubTransportContext,
    query: str,
    variables: dict | None = None,
    *,
    token: str | None = None,
):
    response = bot.github_graphql_request(query, variables, token=token)
    if not response.ok:
        return None
    if response.payload is None:
        return {}
    return response.payload


def post_comment(bot: GitHubTransportContext, issue_number: int, body: str) -> bool:
    return bot.github_api("POST", f"issues/{issue_number}/comments", {"body": body}) is not None


def get_repo_labels(bot: GitHubTransportContext) -> set[str]:
    result = bot.github_api("GET", "labels?per_page=100")
    if result and isinstance(result, list):
        return {label["name"] for label in result}
    return set()


def add_label(bot: GitHubTransportContext, issue_number: int, label: str) -> bool:
    return bot.github_api("POST", f"issues/{issue_number}/labels", {"labels": [label]}) is not None


def remove_label(bot: GitHubTransportContext, issue_number: int, label: str) -> bool:
    bot.github_api("DELETE", f"issues/{issue_number}/labels/{quote(label, safe='')}")
    return True


def add_label_with_status(bot: GitHubTransportContext, issue_number: int, label: str) -> bool:
    response = bot.github_api_request(
        "POST",
        f"issues/{issue_number}/labels",
        {"labels": [label]},
        suppress_error_log=True,
    )
    if response.status_code in {200, 201}:
        return True
    if response.status_code in {401, 403}:
        raise RuntimeError(
            f"Permission denied adding label '{label}' to #{issue_number}: {response.text}"
        )
    print(
        f"WARNING: Failed to add label '{label}' to #{issue_number} "
        f"(status {response.status_code}): {response.text}",
        file=sys.stderr,
    )
    return False


def remove_label_with_status(bot: GitHubTransportContext, issue_number: int, label: str) -> bool:
    response = bot.github_api_request(
        "DELETE",
        f"issues/{issue_number}/labels/{quote(label, safe='')}",
        suppress_error_log=True,
    )
    if response.status_code in {200, 204, 404}:
        return True
    if response.status_code in {401, 403}:
        raise RuntimeError(
            f"Permission denied removing label '{label}' from #{issue_number}: {response.text}"
        )
    print(
        f"WARNING: Failed to remove label '{label}' from #{issue_number} "
        f"(status {response.status_code}): {response.text}",
        file=sys.stderr,
    )
    return False


def ensure_label_exists(
    bot: GitHubTransportContext,
    label: str,
    *,
    color: str | None = None,
    description: str | None = None,
) -> bool:
    label_config = STATUS_LABEL_CONFIG.get(label, {})
    response = bot.github_api_request(
        "POST",
        "labels",
        {
            "name": label,
            "color": color or label_config.get("color", "d73a4a"),
            "description": description or label_config.get("description", ""),
        },
        suppress_error_log=True,
    )

    if response.status_code in {201, 422}:
        return True

    print(
        f"WARNING: Failed to ensure label '{label}' exists (status {response.status_code}): "
        f"{response.text}",
        file=sys.stderr,
    )
    return False


def request_reviewer_assignment(bot: GitHubTransportContext, issue_number: int, username: str):
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    if is_pr:
        endpoint = f"pulls/{issue_number}/requested_reviewers"
        payload = {"reviewers": [username]}
        assignment_target = "PR reviewer"
    else:
        endpoint = f"issues/{issue_number}/assignees"
        payload = {"assignees": [username]}
        assignment_target = "issue assignee"

    lock_api_retry_limit = getattr(bot, "LOCK_API_RETRY_LIMIT", LOCK_API_RETRY_LIMIT)
    lock_retry_base_seconds = getattr(bot, "LOCK_RETRY_BASE_SECONDS", LOCK_RETRY_BASE_SECONDS)

    for attempt in range(1, lock_api_retry_limit + 1):
        response = bot.github_api_request("POST", endpoint, payload, suppress_error_log=True)
        if response.status_code in {200, 201}:
            return bot.AssignmentAttempt(success=True, status_code=response.status_code)
        if response.status_code == 422:
            return bot.AssignmentAttempt(success=False, status_code=422)
        if response.status_code in {401, 403}:
            raise RuntimeError(
                f"Permission denied requesting {assignment_target} @{username} on "
                f"#{issue_number} (status {response.status_code}): {response.text}"
            )
        if response.status_code == 429 or response.status_code >= 500:
            if attempt < lock_api_retry_limit:
                delay = lock_retry_base_seconds + random.uniform(0, lock_retry_base_seconds)
                print(
                    f"Retryable {assignment_target} API failure for @{username} on #{issue_number} "
                    f"(status {response.status_code}); retrying ({attempt}/{lock_api_retry_limit})"
                )
                time.sleep(delay)
                continue
            return bot.AssignmentAttempt(
                success=False,
                status_code=response.status_code,
                exhausted_retryable_failure=True,
            )

        print(
            f"WARNING: Unexpected {assignment_target} API status {response.status_code} "
            f"for @{username} on #{issue_number}: {response.text}",
            file=sys.stderr,
        )
        return bot.AssignmentAttempt(success=False, status_code=response.status_code)

    return bot.AssignmentAttempt(success=False, status_code=None, exhausted_retryable_failure=True)


def assign_reviewer(bot: GitHubTransportContext, issue_number: int, username: str) -> bool:
    return bot.request_reviewer_assignment(issue_number, username).success


def get_assignment_failure_comment(bot: GitHubTransportContext, reviewer: str, attempt) -> str | None:
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    if attempt.status_code == 422:
        if is_pr:
            return bot.REVIEWER_REQUEST_422_TEMPLATE.format(reviewer=reviewer)
        return (
            f"@{reviewer} is designated as reviewer by queue rotation, but GitHub could not "
            "add them as an assignee automatically (API 422)."
        )

    if attempt.exhausted_retryable_failure:
        return (
            f"@{reviewer} is designated as reviewer by queue rotation, but GitHub could not "
            f"add them to PR Reviewers automatically after retries (status {attempt.status_code}). "
            "A triage+ approver may still be required before merge queue."
        )
    return None


def get_issue_assignees(bot: GitHubTransportContext, issue_number: int) -> list[str]:
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    if is_pr:
        result = bot.github_api("GET", f"pulls/{issue_number}")
        if result and "requested_reviewers" in result:
            return [reviewer["login"] for reviewer in result["requested_reviewers"]]
    else:
        result = bot.github_api("GET", f"issues/{issue_number}")
        if result and "assignees" in result:
            return [assignee["login"] for assignee in result["assignees"]]
    return []


def add_reaction(bot: GitHubTransportContext, comment_id: int, reaction: str) -> bool:
    return (
        bot.github_api("POST", f"issues/comments/{comment_id}/reactions", {"content": reaction})
        is not None
    )


def remove_assignee(bot: GitHubTransportContext, issue_number: int, username: str) -> bool:
    return (
        bot.github_api("DELETE", f"issues/{issue_number}/assignees", {"assignees": [username]})
        is not None
    )


def remove_pr_reviewer(bot: GitHubTransportContext, issue_number: int, username: str) -> bool:
    return (
        bot.github_api(
            "DELETE",
            f"pulls/{issue_number}/requested_reviewers",
            {"reviewers": [username]},
        )
        is not None
    )


def unassign_reviewer(bot: GitHubTransportContext, issue_number: int, username: str) -> bool:
    is_pr = os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"
    if is_pr:
        bot.remove_pr_reviewer(issue_number, username)
    return bot.remove_assignee(issue_number, username)


def check_user_permission(bot: GitHubTransportContext, username: str, required_permission: str = "triage") -> bool:
    result = bot.github_api("GET", f"collaborators/{username}/permission")
    if not result:
        return False
    permissions = result.get("user", {}).get("permissions", {})
    return permissions.get(required_permission, False)
