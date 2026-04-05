from __future__ import annotations

import json
from copy import deepcopy
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

    def stub_state_sequence(self, *states: dict) -> None:
        state_queue = [deepcopy(state) for state in states]

        def fake_load_state(*, fail_on_unavailable: bool = False):
            del fail_on_unavailable
            if not state_queue:
                raise AssertionError("No more fake states queued")
            if len(state_queue) == 1:
                return state_queue[0]
            return state_queue.pop(0)

        self.stub_load(fake_load_state)

    def stub_state_unavailable(self, message: str = "state unavailable") -> None:
        def fake_load_state(*, fail_on_unavailable: bool = False):
            assert fail_on_unavailable is True
            raise RuntimeError(message)

        self.stub_load(fake_load_state)

    def record_saves(self, snapshots: list) -> None:
        def fake_save_state(state: dict) -> bool:
            snapshots.append(json.loads(json.dumps(state)))
            return True

        self.stub_save(fake_save_state)

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
        self._runtime = None

    def bind_runtime(self, runtime) -> None:
        self._runtime = runtime

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

    def _runtime_required(self):
        if self._runtime is None:
            raise AssertionError("GitHubStub runtime not bound")
        return self._runtime

    def _instance_override(self, name: str):
        runtime = self._runtime_required()
        override = runtime.__dict__.get(name)
        return override if callable(override) else None

    def get_github_token(self):
        override = self._instance_override("get_github_token")
        if override is not None:
            return override()
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.get_github_token(self._runtime_required())

    def get_github_graphql_token(self, *, prefer_board_token=False):
        override = self._instance_override("get_github_graphql_token")
        if override is not None:
            return override(prefer_board_token=prefer_board_token)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.get_github_graphql_token(self._runtime_required(), prefer_board_token=prefer_board_token)

    def github_graphql(self, query, variables=None, *, token=None):
        override = self._instance_override("github_graphql")
        if override is not None:
            return override(query, variables, token=token)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.github_graphql(self._runtime_required(), query, variables, token=token)

    def post_comment(self, issue_number: int, body: str):
        override = self._instance_override("post_comment")
        if override is not None:
            return override(issue_number, body)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.post_comment(self._runtime_required(), issue_number, body)

    def get_repo_labels(self):
        override = self._instance_override("get_repo_labels")
        if override is not None:
            return override()
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.get_repo_labels(self._runtime_required())

    def add_label(self, issue_number: int, label: str):
        override = self._instance_override("add_label")
        if override is not None:
            return override(issue_number, label)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.add_label(self._runtime_required(), issue_number, label)

    def remove_label(self, issue_number: int, label: str):
        override = self._instance_override("remove_label")
        if override is not None:
            return override(issue_number, label)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.remove_label(self._runtime_required(), issue_number, label)

    def ensure_label_exists(self, label: str, *, color=None, description=None):
        override = self._instance_override("ensure_label_exists")
        if override is not None:
            return override(label, color=color, description=description)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.ensure_label_exists(self._runtime_required(), label, color=color, description=description)

    def get_issue_assignees(self, issue_number: int):
        override = self._instance_override("get_issue_assignees")
        if override is not None:
            return override(issue_number)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.get_issue_assignees(self._runtime_required(), issue_number)

    def request_reviewer_assignment(self, issue_number: int, username: str):
        override = self._instance_override("request_reviewer_assignment")
        if override is not None:
            return override(issue_number, username)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.request_reviewer_assignment(self._runtime_required(), issue_number, username)

    def get_assignment_failure_comment(self, reviewer: str, attempt):
        override = self._instance_override("get_assignment_failure_comment")
        if override is not None:
            return override(reviewer, attempt)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.get_assignment_failure_comment(self._runtime_required(), reviewer, attempt)

    def add_reaction(self, comment_id: int, reaction: str):
        override = self._instance_override("add_reaction")
        if override is not None:
            return override(comment_id, reaction)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.add_reaction(self._runtime_required(), comment_id, reaction)

    def remove_assignee(self, issue_number: int, username: str):
        override = self._instance_override("remove_assignee")
        if override is not None:
            return override(issue_number, username)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.remove_assignee(self._runtime_required(), issue_number, username)

    def remove_pr_reviewer(self, issue_number: int, username: str):
        override = self._instance_override("remove_pr_reviewer")
        if override is not None:
            return override(issue_number, username)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.remove_pr_reviewer(self._runtime_required(), issue_number, username)

    def unassign_reviewer(self, issue_number: int, username: str):
        override = self._instance_override("unassign_reviewer")
        if override is not None:
            return override(issue_number, username)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.unassign_reviewer(self._runtime_required(), issue_number, username)

    def get_user_permission_status(self, username: str, required_permission="triage"):
        override = self._instance_override("get_user_permission_status")
        if override is not None:
            return override(username, required_permission)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.get_user_permission_status(self._runtime_required(), username, required_permission)

    def check_user_permission(self, username: str, required_permission="triage"):
        override = self._instance_override("check_user_permission")
        if override is not None:
            return override(username, required_permission)
        from scripts.reviewer_bot_lib import github_api as github_api_module

        return github_api_module.check_user_permission(self._runtime_required(), username, required_permission)

    def get_issue_or_pr_snapshot(self, issue_number: int):
        override = self._instance_override("get_issue_or_pr_snapshot")
        if override is not None:
            return override(issue_number)
        return self.github_api("GET", f"issues/{issue_number}")

    def get_pull_request_reviews(self, issue_number: int):
        override = self._instance_override("get_pull_request_reviews")
        if override is not None:
            return override(issue_number)
        from scripts.reviewer_bot_lib import reviews as reviews_module

        return reviews_module.get_pull_request_reviews(self._runtime_required(), issue_number)


class RestTransportStub:
    def __init__(self, github_stub: GitHubStub):
        self._github = github_stub
        self.calls: list[dict[str, Any]] = []
        self._direct_request: Callable[..., Any] | None = None

    def stub(self, func: Callable[..., Any]) -> None:
        self._direct_request = func

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
        if self._direct_request is not None and (len(parts) < 4 or parts[0] != "repos"):
            return self._direct_request(
                method=method,
                url=url,
                headers=headers,
                json_data=json_data,
                timeout_seconds=timeout_seconds,
            )
        if len(parts) >= 4 and parts[0] == "repos":
            endpoint = "/".join(parts[3:])
        else:
            endpoint = parsed.path.lstrip("/")
        result = self._github.github_api_request(method, endpoint, data=json_data)

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
        self._query: Callable[..., Any] | None = lambda **kwargs: (_ for _ in ()).throw(AssertionError("No GraphQL stub configured"))
        self._sequence: list[Any] | None = None
        self.calls: list[dict[str, Any]] = []

    def stub(self, func: Callable[..., Any]) -> None:
        self._sequence = None
        self._query = func

    def stub_sequence(self, responses: list[Any]) -> None:
        if not responses:
            raise ValueError("response sequence cannot be empty")
        self._query = None
        self._sequence = list(responses)

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
        if self._sequence is not None:
            response = self._sequence[0]
            if len(self._sequence) > 1:
                del self._sequence[0]
            if isinstance(response, Exception):
                raise response
            return response
        assert self._query is not None
        return self._query(url=url, headers=headers, query=query, variables=variables, timeout_seconds=timeout_seconds)


class ArtifactDownloadTransportStub:
    def __init__(self):
        self._download: Callable[..., Any] | None = lambda **kwargs: (_ for _ in ()).throw(AssertionError("No artifact download stub configured"))
        self._sequence: list[Any] | None = None
        self.calls: list[dict[str, Any]] = []

    def stub(self, func: Callable[..., Any]) -> None:
        self._sequence = None
        self._download = func

    def stub_sequence(self, responses: list[Any]) -> None:
        if not responses:
            raise ValueError("response sequence cannot be empty")
        self._download = None
        self._sequence = list(responses)

    def download(self, url: str, *, headers=None, timeout_seconds=None):
        self.calls.append({"url": url, "headers": headers, "timeout_seconds": timeout_seconds})
        if self._sequence is not None:
            response = self._sequence[0]
            if len(self._sequence) > 1:
                del self._sequence[0]
            if isinstance(response, Exception):
                raise response
            return response
        assert self._download is not None
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


class WorkflowBehaviorStub:
    def __init__(self):
        self._process_pass_until: Callable[[dict], tuple[dict, list[str]]] = lambda state: (state, [])
        self._sync_members: Callable[[dict], tuple[dict, list[str]]] = lambda state: (state, [])
        self._sync_status_labels: Callable[[dict, Any], bool] = lambda state, issue_numbers: False

    def process_pass_until_expirations(self, state: dict):
        return self._process_pass_until(state)

    def sync_members_with_queue(self, state: dict):
        return self._sync_members(state)

    def sync_status_labels_for_items(self, state: dict, issue_numbers):
        return self._sync_status_labels(state, issue_numbers)

    def stub_pass_until(self, func: Callable[[dict], tuple[dict, list[str]]]) -> None:
        self._process_pass_until = func

    def stub_sync_members(self, func: Callable[[dict], tuple[dict, list[str]]]) -> None:
        self._sync_members = func

    def stub_sync_status_labels(self, func: Callable[[dict, Any], bool]) -> None:
        self._sync_status_labels = func
