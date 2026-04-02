from __future__ import annotations

from dataclasses import dataclass

from scripts import reviewer_bot

from .fake_runtime import FakeReviewerBotRuntime


@dataclass
class MainRun:
    exit_code: int | None
    context: reviewer_bot.EventContext | None = None


class AppHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.runtime = FakeReviewerBotRuntime(monkeypatch)
        self.config = self.runtime.config
        self.outputs = self.runtime.outputs
        self._monkeypatch.setattr(reviewer_bot, "RUNTIME", self.runtime)

    def set_event(self, **values) -> None:
        for name, value in values.items():
            self.config.set(name, value)

    def set_state_sequence(self, *states: dict) -> None:
        self.runtime.stub_state_sequence(*states)

    def stub_execute_run(self, result: reviewer_bot.ExecutionResult) -> MainRun:
        captured = MainRun(exit_code=None)

        def fake_execute_run(bot, context):
            captured.context = context
            return result

        self._monkeypatch.setattr(reviewer_bot.app_module, "execute_run", fake_execute_run)
        return captured

    def run_execute(self):
        return reviewer_bot.execute_run(reviewer_bot.build_event_context())

    def run_main(self) -> MainRun:
        try:
            reviewer_bot.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            return MainRun(exit_code=code)
        return MainRun(exit_code=None)
