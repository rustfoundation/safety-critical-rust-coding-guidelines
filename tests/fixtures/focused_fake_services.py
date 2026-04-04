from __future__ import annotations

import json
from typing import Any, Callable
from urllib.parse import urlparse


class ConfigBag:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.values: dict[str, str] = {}

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)

    def set(self, name: str, value) -> None:
        rendered = str(value)
        self.values[name] = rendered
        self._monkeypatch.setenv(name, rendered)


class OutputCapture:
    def __init__(self):
        self.writes: list[tuple[str, str]] = []

    def write(self, name: str, value: str) -> None:
        self.writes.append((name, value))


class DeferredPayloadStore:
    def __init__(self):
        self._payload: dict = {}

    def set_payload(self, payload: dict) -> None:
        self._payload = payload

    def load(self) -> dict:
        return self._payload


class StateStoreStub:
    def __init__(self):
        self._load: Callable[..., dict] = lambda *, fail_on_unavailable=False: {"active_reviews": {}}
        self._save: Callable[[dict], bool] = lambda state: True

    def stub_load(self, func: Callable[..., dict]) -> None:
        self._load = func

    def stub_save(self, func: Callable[[dict], bool]) -> None:
        self._save = func

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self._load(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self._save(state)


class LockStub:
    def __init__(self):
        self._acquire: Callable[[], Any] = lambda: None
        self._release: Callable[[], bool] = lambda: True
        self._refresh: Callable[[], bool] = lambda: True

    def stub(self, *, acquire=None, release=None, refresh=None) -> None:
        if acquire is not None:
            self._acquire = acquire
        if release is not None:
            self._release = release
        if refresh is not None:
            self._refresh = refresh

    def acquire(self):
        return self._acquire()

    def release(self) -> bool:
        return self._release()

    def refresh(self) -> bool:
        return self._refresh()


class GitHubStub:
    def __init__(self, github=None):
        self._github = github

    def stub(self, github) -> None:
        self._github = github

    def github_api(self, method: str, endpoint: str, data=None):
        if self._github is None:
            raise AssertionError(f"No GitHub stub configured for {method} {endpoint}")
        return self._github.github_api(method, endpoint, data=data)

    def github_api_request(self, method: str, endpoint: str, data=None, extra_headers=None, **kwargs):
        if self._github is None:
            raise AssertionError(f"No GitHub request stub configured for {method} {endpoint}")
        return self._github.github_api_request(
            method,
            endpoint,
            data=data,
            extra_headers=extra_headers,
            **kwargs,
        )


class RestTransportStub:
    def __init__(self, runtime):
        self._runtime = runtime
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, *, headers=None, json_data=None, timeout_seconds=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json_data": json_data,
                "timeout_seconds": timeout_seconds,
            }
        )
        parsed = urlparse(url)
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "repos":
            endpoint = "/".join(parts[3:])
        else:
            endpoint = parsed.path.lstrip("/")
        result = self._runtime.github_api_request(method, endpoint, data=json_data)

        class _Response:
            def __init__(self, api_result):
                self.status_code = api_result.status_code or 0
                self.headers = api_result.headers
                self.text = api_result.text
                self._payload = api_result.payload
                if api_result.payload is None:
                    self.content = b""
                elif isinstance(api_result.payload, Exception):
                    self.content = b"invalid-json"
                else:
                    self.content = json.dumps(api_result.payload).encode("utf-8")

            def json(self):
                if isinstance(self._payload, Exception):
                    raise self._payload
                return self._payload

        return _Response(result)


class GraphQLTransportStub:
    def __init__(self):
        self._query: Callable[..., Any] = lambda **kwargs: (_ for _ in ()).throw(AssertionError("No GraphQL stub configured"))
        self.calls: list[dict[str, Any]] = []

    def stub(self, func: Callable[..., Any]) -> None:
        self._query = func

    def query(self, url: str, *, headers=None, query: str, variables=None, timeout_seconds=None):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "query": query,
                "variables": variables,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self._query(url=url, headers=headers, query=query, variables=variables, timeout_seconds=timeout_seconds)


class ArtifactDownloadTransportStub:
    def __init__(self):
        self._download: Callable[..., Any] = lambda **kwargs: (_ for _ in ()).throw(AssertionError("No artifact download stub configured"))
        self.calls: list[dict[str, Any]] = []

    def stub(self, func: Callable[..., Any]) -> None:
        self._download = func

    def download(self, url: str, *, headers=None, timeout_seconds=None):
        self.calls.append({"url": url, "headers": headers, "timeout_seconds": timeout_seconds})
        return self._download(url=url, headers=headers, timeout_seconds=timeout_seconds)


class HandlerStub:
    ALLOWED = {
        "handle_issue_or_pr_opened",
        "handle_labeled_event",
        "handle_issue_edited_event",
        "handle_closed_event",
        "handle_pull_request_target_synchronize",
        "handle_pull_request_review_event",
        "handle_comment_event",
        "handle_manual_dispatch",
        "handle_scheduled_check",
        "handle_workflow_run_event",
    }

    def __init__(self, defaults: dict[str, Callable[[dict], bool]]):
        self._handlers: dict[str, Callable[[dict], bool]] = defaults

    def stub(self, name: str, func: Callable[[dict], bool]) -> None:
        if name not in self.ALLOWED:
            raise AssertionError(f"Unsupported runtime handler override: {name}")
        self._handlers[name] = func

    def call(self, name: str, state: dict) -> bool:
        return self._handlers[name](state)

    def __getattr__(self, name: str):
        if name in self.ALLOWED:
            return lambda state: self._handlers[name](state)
        raise AttributeError(name)


class TouchTrackerStub:
    def __init__(self):
        self._touched: list[int] = []

    def collect(self, issue_number: int | None) -> None:
        if isinstance(issue_number, int) and issue_number not in self._touched:
            self._touched.append(issue_number)

    def drain(self) -> list[int]:
        items = list(self._touched)
        self._touched.clear()
        return items
