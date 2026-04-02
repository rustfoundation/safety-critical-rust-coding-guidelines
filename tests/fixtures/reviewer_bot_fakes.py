from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from scripts import reviewer_bot


def github_result(
    status_code: int,
    payload: Any = None,
    *,
    headers: dict[str, str] | None = None,
    text: str | None = None,
    ok: bool | None = None,
    failure_kind: str | None = None,
    retry_attempts: int = 0,
    transport_error: str | None = None,
) -> reviewer_bot.GitHubApiResult:
    normalized_headers = {
        key.lower(): value for key, value in (headers or {}).items()
    }
    resolved_ok = status_code < 400 if ok is None else ok
    resolved_failure_kind = failure_kind
    if resolved_failure_kind is None and not resolved_ok:
        if status_code == 404:
            resolved_failure_kind = "not_found"
        elif status_code == 429:
            resolved_failure_kind = "rate_limited"
        elif status_code is not None and status_code >= 500:
            resolved_failure_kind = "server_error"
        else:
            resolved_failure_kind = "http_error"
    resolved_text = text
    if resolved_text is None:
        if isinstance(payload, dict) and isinstance(payload.get("message"), str):
            resolved_text = payload["message"]
        elif payload is None:
            resolved_text = ""
        else:
            resolved_text = "ok" if resolved_ok else "error"
    return reviewer_bot.GitHubApiResult(
        status_code=status_code,
        payload=payload,
        headers=normalized_headers,
        text=resolved_text,
        ok=resolved_ok,
        failure_kind=resolved_failure_kind,
        retry_attempts=retry_attempts,
        transport_error=transport_error,
    )


@dataclass(frozen=True)
class GitHubCall:
    method: str
    endpoint: str
    data: dict | None
    extra_headers: dict[str, str] | None = None
    kwargs: dict[str, Any] | None = None


class RouteGitHubApi:
    def __init__(self):
        self._request_routes: dict[tuple[str, str], reviewer_bot.GitHubApiResult] = {}
        self._api_routes: dict[tuple[str, str], Any] = {}
        self._raise_system_exit_on_request = False
        self.request_calls: list[GitHubCall] = []
        self.api_calls: list[GitHubCall] = []

    def add_request(
        self,
        method: str,
        endpoint: str,
        result: reviewer_bot.GitHubApiResult | None = None,
        **result_kwargs,
    ) -> "RouteGitHubApi":
        self._request_routes[(method, endpoint)] = result or github_result(**result_kwargs)
        return self

    def add_api(self, method: str, endpoint: str, payload: Any) -> "RouteGitHubApi":
        self._api_routes[(method, endpoint)] = payload
        return self

    def raise_system_exit_on_request(self) -> "RouteGitHubApi":
        self._raise_system_exit_on_request = True
        return self

    def requested_endpoints(self) -> list[str]:
        return [call.endpoint for call in self.request_calls]

    def api_endpoints(self) -> list[str]:
        return [call.endpoint for call in self.api_calls]

    def github_api_request(
        self,
        method: str,
        endpoint: str,
        data: dict | None = None,
        extra_headers: dict[str, str] | None = None,
        **kwargs,
    ) -> reviewer_bot.GitHubApiResult:
        self.request_calls.append(
            GitHubCall(
                method=method,
                endpoint=endpoint,
                data=data,
                extra_headers=extra_headers,
                kwargs=kwargs,
            )
        )
        if self._raise_system_exit_on_request:
            raise SystemExit(1)
        route = self._request_routes.get((method, endpoint))
        if route is None:
            raise AssertionError(f"Unexpected GitHub request route: {method} {endpoint}")
        return route

    def github_api(self, method: str, endpoint: str, data: dict | None = None):
        self.api_calls.append(
            GitHubCall(method=method, endpoint=endpoint, data=data)
        )
        key = (method, endpoint)
        if key in self._api_routes:
            return self._api_routes[key]
        route = self._request_routes.get(key)
        if route is None:
            raise AssertionError(f"Unexpected GitHub API route: {method} {endpoint}")
        if not route.ok:
            return None
        if route.payload is None:
            return {}
        return route.payload
