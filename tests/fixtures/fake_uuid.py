from __future__ import annotations


class FixedUuidSource:
    def __init__(self, values: str | list[str] = "fixed-uuid"):
        self._values = [values] if isinstance(values, str) else list(values)
        self.issued: list[str] = []
        self._index = 0

    def uuid4_hex(self) -> str:
        if not self._values:
            value = "fixed-uuid"
        elif self._index >= len(self._values):
            value = self._values[-1]
        else:
            value = self._values[self._index]
            self._index += 1
        self.issued.append(value)
        return value
