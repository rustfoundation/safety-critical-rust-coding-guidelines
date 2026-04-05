from __future__ import annotations

from datetime import datetime, timedelta, timezone


class FakeClock:
    def __init__(self, now: datetime | None = None):
        self._now = now or datetime(2026, 1, 1, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now

    def advance(self, *, seconds: float = 0, delta: timedelta | None = None) -> datetime:
        self._now = self._now + (delta or timedelta(seconds=seconds))
        return self._now
