from __future__ import annotations


class RecordingLogger:
    def __init__(self):
        self.records: list[dict[str, object]] = []

    def event(self, level: str, message: str, **fields) -> None:
        self.records.append(
            {
                "level": level,
                "message": message,
                "fields": dict(fields),
            }
        )
