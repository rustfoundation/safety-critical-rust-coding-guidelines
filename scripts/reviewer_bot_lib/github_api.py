"""GitHub transport and issue/PR mutation helpers."""

import json
import random
import time
from urllib.parse import quote

import requests

from . import retrying
from .config import (
    LOCK_API_RETRY_LIMIT,
    LOCK_RETRY_BASE_SECONDS,
    REVIEWER_BOARD_TOKEN_ENV,
    STATUS_LABEL_CONFIG,
)
from .context import GitHubApiContext, GitHubTransportContext

RETRY_POLICY_NONE = retrying.RETRY_POLICY_NONE
RETRY_POLICY_IDEMPOTENT_READ = retrying.RETRY_POLICY_IDEMPOTENT_READ


class _RandomJitter:
    def uniform(self, lower: float, upper: float) -> float:
        return random.uniform(lower, upper)


def _log(bot: GitHubApiContext, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def _sleep(bot: GitHubApiContext, seconds: float) -> None:
    sleeper = getattr(bot, "sleeper", None)
    if sleeper is not None and hasattr(sleeper, "sleep"):
        sleeper.sleep(seconds)
        return
    time.sleep(seconds)


def _retry_delay(bot: GitHubApiContext, base_seconds: float, retry_attempt: int) -> float:
    return retrying.bounded_exponential_delay(
        base_seconds,
        retry_attempt,
        jitter=getattr(bot, "jitter", None) or _RandomJitter(),
    )


def _is_pull_request(bot: GitHubApiContext) -> bool:
    return bot.get_config_value("IS_PULL_REQUEST", "false").lower() == "true"


def _should_retry_status(status_code: int | None) -> bool:
    return retrying.is_retryable_status(status_code)


def _classify_failure(status_code: int | None, *, invalid_payload: bool = False, transport_error: bool = False) -> str | None:
    if invalid_payload:
        return "invalid_payload"
    if transport_error:
        return "transport_error"
    if status_code is None:
        return None
    if status_code == 404:
        return "not_found"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "server_error"
    return None


def _validate_rest_retry_policy(method: str, retry_policy: str) -> None:
    retrying.additional_attempts_for_policy(retry_policy, LOCK_API_RETRY_LIMIT)
    if retry_policy == RETRY_POLICY_NONE:
        return
    if method.upper() != "GET":
        raise ValueError("idempotent_read retry policy is only valid for REST GET requests")


def _validate_graphql_retry_policy(query: str, retry_policy: str) -> None:
    retrying.additional_attempts_for_policy(retry_policy, LOCK_API_RETRY_LIMIT)
    if retry_policy == RETRY_POLICY_NONE:
        return
    stripped = query.lstrip()
    if stripped.startswith("mutation"):
        raise ValueError("idempotent_read retry policy is only valid for GraphQL queries")


def _build_result(
    bot: GitHubTransportContext,
    *,
    status_code: int | None,
    payload,
    headers: dict[str, str] | None,
    text: str,
    ok: bool,
    failure_kind: str | None,
    retry_attempts: int,
    transport_error: str | None = None,
):
    return bot.GitHubApiResult(
        status_code=status_code,
        payload=payload,
        headers=headers or {},
        text=text,
        ok=ok,
        failure_kind=failure_kind,
        retry_attempts=retry_attempts,
        transport_error=transport_error,
    )


def get_github_token(bot: GitHubApiContext) -> str:
    token = bot.get_config_value("GITHUB_TOKEN")
    if not token:
        _log(bot, "error", "GITHUB_TOKEN not set")
        raise SystemExit(1)
    return token


def get_github_graphql_token(bot: GitHubApiContext, *, prefer_board_token: bool = False) -> str:
    if prefer_board_token:
        token = bot.get_config_value(REVIEWER_BOARD_TOKEN_ENV)
        if not token:
            raise RuntimeError(f"{REVIEWER_BOARD_TOKEN_ENV} not set")
        return token
    return bot.get_github_token()


def github_api_request(
    bot: GitHubApiContext,
    method: str,
    endpoint: str,
    data: dict | None = None,
    extra_headers: dict[str, str] | None = None,
    *,
    retry_policy: str = RETRY_POLICY_NONE,
    timeout_seconds: float | None = None,
    suppress_error_log: bool = False,
):
    _validate_rest_retry_policy(method, retry_policy)
    token = bot.get_github_token()
    repo = f"{bot.get_config_value('REPO_OWNER')}/{bot.get_config_value('REPO_NAME')}"
    url = f"https://api.github.com/repos/{repo}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if extra_headers:
        headers.update(extra_headers)

    retry_attempts = 0
    max_attempts = retrying.max_attempts_for_policy(retry_policy, LOCK_API_RETRY_LIMIT)
    for attempt in range(1, max_attempts + 1):
        try:
            response = bot.rest_transport.request(
                method,
                url,
                headers=headers,
                json_data=data,
                timeout_seconds=timeout_seconds,
            )
        except requests.RequestException as exc:
            failure_kind = _classify_failure(None, transport_error=True)
            if attempt < max_attempts:
                retry_attempts += 1
                _sleep(bot, _retry_delay(bot, LOCK_RETRY_BASE_SECONDS, retry_attempts))
                continue
            if not suppress_error_log:
                _log(bot, "error", f"GitHub API transport error: {exc}", transport_error=str(exc))
            return _build_result(
                bot,
                status_code=None,
                payload=None,
                headers={},
                text="",
                ok=False,
                failure_kind=failure_kind,
                retry_attempts=retry_attempts,
                transport_error=str(exc),
            )

        payload = None
        invalid_payload = False
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                invalid_payload = True

        ok = response.status_code < 400 and not invalid_payload
        normalized_headers = {key.lower(): value for key, value in response.headers.items()}
        if ok:
            return _build_result(
                bot,
                status_code=response.status_code,
                payload=payload,
                headers=normalized_headers,
                text=response.text,
                ok=True,
                failure_kind=None,
                retry_attempts=retry_attempts,
            )

        failure_kind = _classify_failure(response.status_code, invalid_payload=invalid_payload)
        if retry_policy == RETRY_POLICY_IDEMPOTENT_READ and _should_retry_status(response.status_code) and attempt < max_attempts:
            retry_attempts += 1
            _sleep(bot, _retry_delay(bot, LOCK_RETRY_BASE_SECONDS, retry_attempts))
            continue

        if not suppress_error_log:
            _log(
                bot,
                "error",
                f"GitHub API error: {response.status_code} - {response.text}",
                status_code=response.status_code,
                failure_kind=failure_kind,
            )
        return _build_result(
            bot,
            status_code=response.status_code,
            payload=payload,
            headers=normalized_headers,
            text=response.text,
            ok=False,
            failure_kind=failure_kind,
            retry_attempts=retry_attempts,
        )

    raise AssertionError("unreachable")


def github_api(bot: GitHubTransportContext, method: str, endpoint: str, data: dict | None = None):
    response = bot.github_api_request(method, endpoint, data)
    if not response.ok:
        return None
    if response.payload is None:
        return {}
    return response.payload


def github_graphql_request(
    bot: GitHubApiContext,
    query: str,
    variables: dict | None = None,
    *,
    token: str | None = None,
    retry_policy: str = RETRY_POLICY_NONE,
    timeout_seconds: float | None = None,
    suppress_error_log: bool = False,
):
    _validate_graphql_retry_policy(query, retry_policy)
    graphql_token = token or bot.get_github_graphql_token()
    headers = {
        "Authorization": f"Bearer {graphql_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    retry_attempts = 0
    max_attempts = retrying.max_attempts_for_policy(retry_policy, LOCK_API_RETRY_LIMIT)
    for attempt in range(1, max_attempts + 1):
        try:
            response = bot.graphql_transport.query(
                "https://api.github.com/graphql",
                headers=headers,
                query=query,
                variables=variables,
                timeout_seconds=timeout_seconds,
            )
        except requests.RequestException as exc:
            failure_kind = _classify_failure(None, transport_error=True)
            if retry_policy == RETRY_POLICY_IDEMPOTENT_READ and attempt < max_attempts:
                retry_attempts += 1
                _sleep(bot, _retry_delay(bot, LOCK_RETRY_BASE_SECONDS, retry_attempts))
                continue
            if not suppress_error_log:
                _log(bot, "error", f"GitHub GraphQL transport error: {exc}", transport_error=str(exc))
            return _build_result(
                bot,
                status_code=None,
                payload=None,
                headers={},
                text="",
                ok=False,
                failure_kind=failure_kind,
                retry_attempts=retry_attempts,
                transport_error=str(exc),
            )

        payload = None
        invalid_payload = False
        if response.content:
            try:
                payload = response.json()
            except ValueError:
                invalid_payload = True

        graphql_errors = payload.get("errors") if isinstance(payload, dict) else None
        ok = response.status_code < 400 and not graphql_errors and not invalid_payload
        normalized_headers = {key.lower(): value for key, value in response.headers.items()}
        if ok:
            return _build_result(
                bot,
                status_code=response.status_code,
                payload=payload,
                headers=normalized_headers,
                text=response.text,
                ok=True,
                failure_kind=None,
                retry_attempts=retry_attempts,
            )

        failure_kind = _classify_failure(
            response.status_code,
            invalid_payload=invalid_payload or bool(graphql_errors),
        )
        if _should_retry_status(response.status_code) and attempt < max_attempts:
            retry_attempts += 1
            _sleep(bot, _retry_delay(bot, LOCK_RETRY_BASE_SECONDS, retry_attempts))
            continue

        if not suppress_error_log:
            details = response.text
            if graphql_errors:
                details = json.dumps(graphql_errors, sort_keys=True)
            _log(
                bot,
                "error",
                f"GitHub GraphQL error: {response.status_code} - {details}",
                status_code=response.status_code,
                failure_kind=failure_kind,
            )
        return _build_result(
            bot,
            status_code=response.status_code,
            payload=payload,
            headers=normalized_headers,
            text=response.text,
            ok=False,
            failure_kind=failure_kind,
            retry_attempts=retry_attempts,
        )

    raise AssertionError("unreachable")


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
    response = bot.github_api_request(
        "DELETE",
        f"issues/{issue_number}/labels/{quote(label, safe='')}",
        suppress_error_log=True,
    )
    return response.status_code in {200, 204, 404}


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
    _log(
        bot,
        "warning",
        f"Failed to add label '{label}' to #{issue_number} (status {response.status_code}): {response.text}",
        issue_number=issue_number,
        label=label,
        status_code=response.status_code,
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
    _log(
        bot,
        "warning",
        f"Failed to remove label '{label}' from #{issue_number} (status {response.status_code}): {response.text}",
        issue_number=issue_number,
        label=label,
        status_code=response.status_code,
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

    _log(
        bot,
        "warning",
        f"Failed to ensure label '{label}' exists (status {response.status_code}): {response.text}",
        label=label,
        status_code=response.status_code,
    )
    return False


def request_reviewer_assignment(bot: GitHubTransportContext, issue_number: int, username: str):
    is_pr = _is_pull_request(bot)
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
                delay = _retry_delay(bot, lock_retry_base_seconds, attempt)
                _log(
                    bot,
                    "warning",
                    f"Retryable {assignment_target} API failure for @{username} on #{issue_number} (status {response.status_code}); retrying ({attempt}/{lock_api_retry_limit})",
                    issue_number=issue_number,
                    username=username,
                    status_code=response.status_code,
                    retry_attempt=attempt,
                )
                _sleep(bot, delay)
                continue
            return bot.AssignmentAttempt(
                success=False,
                status_code=response.status_code,
                exhausted_retryable_failure=True,
            )

        _log(
            bot,
            "warning",
            f"Unexpected {assignment_target} API status {response.status_code} for @{username} on #{issue_number}: {response.text}",
            issue_number=issue_number,
            username=username,
            status_code=response.status_code,
        )
        return bot.AssignmentAttempt(success=False, status_code=response.status_code)

    return bot.AssignmentAttempt(success=False, status_code=None, exhausted_retryable_failure=True)


def assign_reviewer(bot: GitHubTransportContext, issue_number: int, username: str) -> bool:
    return bot.request_reviewer_assignment(issue_number, username).success


def get_assignment_failure_comment(bot: GitHubTransportContext, reviewer: str, attempt) -> str | None:
    is_pr = _is_pull_request(bot)
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


def get_issue_assignees(bot: GitHubTransportContext, issue_number: int) -> list[str] | None:
    is_pr = _is_pull_request(bot)
    if is_pr:
        try:
            response = bot.github_api_request("GET", f"pulls/{issue_number}", retry_policy=RETRY_POLICY_IDEMPOTENT_READ)
            result = response.payload
            if not response.ok:
                return None
        except SystemExit:
            result = bot.github_api("GET", f"pulls/{issue_number}")
        if isinstance(result, dict) and "requested_reviewers" in result:
            return [reviewer["login"] for reviewer in result["requested_reviewers"]]
    else:
        try:
            response = bot.github_api_request("GET", f"issues/{issue_number}", retry_policy=RETRY_POLICY_IDEMPOTENT_READ)
            result = response.payload
            if not response.ok:
                return None
        except SystemExit:
            result = bot.github_api("GET", f"issues/{issue_number}")
        if isinstance(result, dict) and "assignees" in result:
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
    is_pr = _is_pull_request(bot)
    if is_pr:
        bot.remove_pr_reviewer(issue_number, username)
    return bot.remove_assignee(issue_number, username)


def get_user_permission_status(
    bot: GitHubTransportContext,
    username: str,
    required_permission: str = "triage",
) -> str:
    try:
        response = bot.github_api_request(
            "GET",
            f"collaborators/{username}/permission",
            retry_policy=RETRY_POLICY_IDEMPOTENT_READ,
        )
    except SystemExit:
        fallback = getattr(bot, "check_user_permission", None)
        if callable(fallback) and getattr(fallback, "__name__", "") != "check_user_permission":
            result = fallback(username, required_permission)
            if result is None:
                return "unavailable"
            return "granted" if result else "denied"
        return "unavailable"
    if not response.ok:
        return "unavailable"
    result = response.payload
    if not isinstance(result, dict):
        return "unavailable"
    permissions = result.get("user", {}).get("permissions", {})
    if not isinstance(permissions, dict):
        return "unavailable"
    return "granted" if permissions.get(required_permission, False) else "denied"


def check_user_permission(
    bot: GitHubTransportContext,
    username: str,
    required_permission: str = "triage",
) -> bool | None:
    status = get_user_permission_status(bot, username, required_permission)
    if status == "unavailable":
        return None
    return status == "granted"
