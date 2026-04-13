from __future__ import annotations


class RecordingSleeper:
    def __init__(self):
        self.calls: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.calls.append(seconds)
