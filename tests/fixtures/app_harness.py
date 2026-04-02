from __future__ import annotations

from dataclasses import dataclass

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime


class _ConfigBag:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.values: dict[str, str] = {}

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)

    def set(self, name: str, value) -> None:
        rendered = str(value)
        self.values[name] = rendered
        self._monkeypatch.setenv(name, rendered)


class _OutputCapture:
    def __init__(self):
        self.writes: list[tuple[str, str]] = []

    def write(self, name: str, value: str) -> None:
        self.writes.append((name, value))


@dataclass
class MainRun:
    exit_code: int | None
    context: reviewer_bot.EventContext | None = None


class AppHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.config = _ConfigBag(monkeypatch)
        self.outputs = _OutputCapture()
        runtime = ReviewerBotRuntime(
            reviewer_bot,
            config=self.config,
            outputs=self.outputs,
        )
        self._monkeypatch.setattr(reviewer_bot, "RUNTIME", runtime)

    def set_event(self, **values) -> None:
        for name, value in values.items():
            self.config.set(name, value)

    def stub_execute_run(self, result: reviewer_bot.ExecutionResult) -> MainRun:
        captured = MainRun(exit_code=None)

        def fake_execute_run(bot, context):
            captured.context = context
            return result

        self._monkeypatch.setattr(reviewer_bot.app_module, "execute_run", fake_execute_run)
        return captured

    def run_main(self) -> MainRun:
        try:
            reviewer_bot.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            return MainRun(exit_code=code)
        return MainRun(exit_code=None)
