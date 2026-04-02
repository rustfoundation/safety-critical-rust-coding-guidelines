from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from scripts import reviewer_bot


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


class FakeReviewerBotRuntime:
    EVENT_INTENT_MUTATING = reviewer_bot.EVENT_INTENT_MUTATING
    EVENT_INTENT_NON_MUTATING_DEFER = reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER
    EVENT_INTENT_NON_MUTATING_READONLY = reviewer_bot.EVENT_INTENT_NON_MUTATING_READONLY
    STATUS_PROJECTION_EPOCH = reviewer_bot.STATUS_PROJECTION_EPOCH
    datetime = reviewer_bot.datetime
    timezone = reviewer_bot.timezone

    def __init__(self, monkeypatch, *, github=None):
        self._monkeypatch = monkeypatch
        self._module = reviewer_bot
        self._github = github
        self.config = ConfigBag(monkeypatch)
        self.outputs = OutputCapture()
        self._load_state_impl = lambda *, fail_on_unavailable=False: reviewer_bot.load_state(
            fail_on_unavailable=fail_on_unavailable
        )
        self._save_state_impl = lambda state: reviewer_bot.save_state(state)
        self._acquire_impl = lambda: reviewer_bot.acquire_state_issue_lease_lock()
        self._release_impl = lambda: reviewer_bot.release_state_issue_lease_lock()
        self._process_pass_until_impl = lambda state: reviewer_bot.process_pass_until_expirations(state)
        self._sync_members_impl = lambda state: reviewer_bot.sync_members_with_queue(state)
        self._sync_status_labels_impl = lambda state, issue_numbers: reviewer_bot.sync_status_labels_for_items(
            state, issue_numbers
        )
        self._touched_items: list[int] = []

    def __getattr__(self, name: str):
        return getattr(self._module, name)

    def get_config_value(self, name: str, default: str = "") -> str:
        return self.config.get(name, default)

    def set_config_value(self, name: str, value: Any) -> None:
        self.config.set(name, value)

    def write_output(self, name: str, value: str) -> None:
        self.outputs.write(name, value)

    def load_state(self, *, fail_on_unavailable: bool = False) -> dict:
        return self._load_state_impl(fail_on_unavailable=fail_on_unavailable)

    def save_state(self, state: dict) -> bool:
        return self._save_state_impl(state)

    def ensure_state_issue_lease_lock_fresh(self) -> bool:
        return self._module.ensure_state_issue_lease_lock_fresh()

    def acquire_state_issue_lease_lock(self):
        return self._acquire_impl()

    def release_state_issue_lease_lock(self) -> bool:
        return self._release_impl()

    def process_pass_until_expirations(self, state: dict):
        return self._process_pass_until_impl(state)

    def sync_members_with_queue(self, state: dict):
        return self._sync_members_impl(state)

    def sync_status_labels_for_items(self, state: dict, issue_numbers):
        return self._sync_status_labels_impl(state, issue_numbers)

    def handle_issue_or_pr_opened(self, state: dict) -> bool:
        return self._module.handle_issue_or_pr_opened(state)

    def handle_labeled_event(self, state: dict) -> bool:
        return self._module.handle_labeled_event(state)

    def handle_issue_edited_event(self, state: dict) -> bool:
        return self._module.handle_issue_edited_event(state)

    def handle_closed_event(self, state: dict) -> bool:
        return self._module.handle_closed_event(state)

    def handle_pull_request_target_synchronize(self, state: dict) -> bool:
        return self._module.handle_pull_request_target_synchronize(state)

    def handle_pull_request_review_event(self, state: dict) -> bool:
        return self._module.handle_pull_request_review_event(state)

    def handle_comment_event(self, state: dict) -> bool:
        return self._module.handle_comment_event(state)

    def handle_manual_dispatch(self, state: dict) -> bool:
        return self._module.handle_manual_dispatch(state)

    def handle_scheduled_check(self, state: dict) -> bool:
        return self._module.handle_scheduled_check(state)

    def handle_workflow_run_event(self, state: dict) -> bool:
        return self._module.handle_workflow_run_event(state)

    def github_api(self, method: str, endpoint: str, data=None):
        if self._github is not None:
            return self._github.github_api(method, endpoint, data=data)
        return self._module.github_api(method, endpoint, data=data)

    def github_api_request(self, method: str, endpoint: str, data=None, extra_headers=None, **kwargs):
        if self._github is not None:
            return self._github.github_api_request(
                method,
                endpoint,
                data=data,
                extra_headers=extra_headers,
                **kwargs,
            )
        return self._module.github_api_request(
            method,
            endpoint,
            data=data,
            extra_headers=extra_headers,
            **kwargs,
        )

    def collect_touched_item(self, issue_number: int) -> None:
        if issue_number not in self._touched_items:
            self._touched_items.append(issue_number)

    def drain_touched_items(self) -> list[int]:
        items = list(self._touched_items)
        self._touched_items.clear()
        return items

    def stub_state_sequence(self, *states: dict) -> None:
        state_queue = [deepcopy(state) for state in states]

        def fake_load_state(*, fail_on_unavailable: bool = False):
            if not state_queue:
                raise AssertionError("No more fake states queued")
            if len(state_queue) == 1:
                return state_queue[0]
            return state_queue.pop(0)

        self._load_state_impl = fake_load_state

    def stub_state_unavailable(self, message: str = "state unavailable") -> None:
        def fake_load_state(*, fail_on_unavailable: bool = False):
            assert fail_on_unavailable is True
            raise RuntimeError(message)

        self._load_state_impl = fake_load_state

    def record_saves(self, snapshots: list):
        def fake_save_state(state: dict) -> bool:
            snapshots.append(json.loads(json.dumps(state)))
            return True

        self._save_state_impl = fake_save_state

    def set_save_state(self, func) -> None:
        self._save_state_impl = func

    def set_acquire_lock(self, func) -> None:
        self._acquire_impl = func

    def set_release_lock(self, func) -> None:
        self._release_impl = func

    def set_pass_until(self, func) -> None:
        self._process_pass_until_impl = func

    def set_sync_members(self, func) -> None:
        self._sync_members_impl = func

    def set_sync_status_labels(self, func) -> None:
        self._sync_status_labels_impl = func
