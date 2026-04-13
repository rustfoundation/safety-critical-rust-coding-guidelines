from __future__ import annotations

from dataclasses import dataclass

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import app
from scripts.reviewer_bot_lib.context import EventContext, ExecutionResult

from .fake_runtime import FakeReviewerBotRuntime
from .reviewer_bot_env import set_env_values, set_workflow_run_event_payload


@dataclass
class MainRun:
    exit_code: int | None
    context: EventContext | None = None


class AppHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.runtime = FakeReviewerBotRuntime(monkeypatch)
        self.config = self.runtime.config
        self.outputs = self.runtime.outputs
        self.state_store = self.runtime.state_store
        self.locks = self.runtime.locks
        self.handlers = self.runtime.handlers
        self.touch_tracker = self.runtime.touch_tracker

    def set_event(self, **values) -> None:
        set_env_values(self.config, **values)

    def set_workflow_run_name(self, workflow_name: str) -> None:
        set_workflow_run_event_payload(self.config, workflow_name)

    def set_state_sequence(self, *states: dict) -> None:
        self.runtime.stub_state_sequence(*states)

    def stub_load_state(self, func) -> None:
        self.state_store.stub_load(func)

    def stub_save_state(self, func) -> None:
        self.state_store.stub_save(func)

    def stub_lock(self, *, acquire=None, release=None, refresh=None) -> None:
        self.locks.stub(acquire=acquire, release=release, refresh=refresh)

    def stub_handler(self, name: str, func) -> None:
        self.handlers.stub(name, func)

    def stub_pass_until(self, func) -> None:
        self.runtime.stub_pass_until(func)

    def stub_sync_members(self, func) -> None:
        self.runtime.stub_sync_members(func)

    def stub_sync_status_labels(self, func) -> None:
        self.runtime.stub_sync_status_labels(func)

    def stub_execute_run(self, result: ExecutionResult) -> MainRun:
        captured = MainRun(exit_code=None)

        def fake_execute_run(bot, context):
            captured.context = context
            return result

        self._monkeypatch.setattr(app, "execute_run", fake_execute_run)
        return captured

    def run_execute(self):
        return reviewer_bot.execute_run(reviewer_bot.build_event_context(self.runtime), self.runtime)

    def run_main(self) -> MainRun:
        try:
            reviewer_bot.main(self.runtime)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            return MainRun(exit_code=code)
        return MainRun(exit_code=None)
