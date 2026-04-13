from __future__ import annotations


class DeterministicJitter:
    def __init__(self, values: float | list[float] = 0.0):
        self._values = [float(values)] if isinstance(values, (float, int)) else [float(value) for value in values]
        self.calls: list[tuple[float, float]] = []
        self._index = 0

    def uniform(self, lower: float, upper: float) -> float:
        self.calls.append((lower, upper))
        if not self._values:
            return lower
        if self._index >= len(self._values):
            return float(self._values[-1])
        value = float(self._values[self._index])
        self._index += 1
        return value
