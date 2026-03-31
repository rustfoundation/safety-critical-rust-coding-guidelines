"""Concrete runtime object for reviewer-bot orchestration."""

from __future__ import annotations

from types import ModuleType
from typing import Any


class ReviewerBotRuntime:
    """Thin compatibility wrapper around the adapter module.

    The first slice is intentionally structural only: it delegates all runtime
    reads and writes to the existing adapter module so current wrappers,
    monkeypatching patterns, and mutable state remain behavior-compatible.
    """

    def __init__(self, module: ModuleType):
        object.__setattr__(self, "_module", module)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._module, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name == "_module":
            object.__setattr__(self, name, value)
            return
        setattr(self._module, name, value)
