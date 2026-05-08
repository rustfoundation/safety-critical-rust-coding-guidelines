"""Reminder comment scan and diff helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .config import TRANSITION_NOTICE_MARKER_PREFIX, TRANSITION_WARNING_MARKER_PREFIX


@dataclass(frozen=True)
class ReminderCommentRecord:
    comment_id: int | str
    author_login: str
    created_at: str
    body_first_line: str
    matched_shape: str
    url: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "comment_id": self.comment_id,
            "author_login": self.author_login,
            "created_at": self.created_at,
            "body_first_line": self.body_first_line,
            "matched_shape": self.matched_shape,
            "url": self.url,
        }


@dataclass(frozen=True)
class ReminderCommentScan:
    records: tuple[ReminderCommentRecord, ...]
    baseline_count: int
    baseline_latest_created_at: str | None
    scan_status: str

    def to_output(self) -> dict[str, object]:
        return {
            "records": [record.to_output() for record in _sort_records(self.records)],
            "baseline_count": self.baseline_count,
            "baseline_latest_created_at": self.baseline_latest_created_at,
            "scan_status": self.scan_status,
        }


@dataclass(frozen=True)
class ReminderCommentDiff:
    before_count: int
    after_count: int
    new_records: tuple[ReminderCommentRecord, ...]
    diff_status: str

    def to_output(self) -> dict[str, object]:
        return {
            "before_count": self.before_count,
            "after_count": self.after_count,
            "new_records": [record.to_output() for record in _sort_records(self.new_records)],
            "diff_status": self.diff_status,
        }


_REMINDER_AUTHORS = {"github-actions[bot]", "guidelines-bot", "github-actions"}


def _sort_records(records: tuple[ReminderCommentRecord, ...]) -> tuple[ReminderCommentRecord, ...]:
    return tuple(sorted(records, key=lambda record: (record.created_at, str(record.comment_id), record.matched_shape)))


def _first_line(body: str) -> str:
    lines = body.splitlines()
    return lines[0].strip() if lines else ""


def _matched_shape(first_line: str, body: str) -> str | None:
    if first_line.startswith(f"<!-- {TRANSITION_WARNING_MARKER_PREFIX} "):
        return "markerized_warning"
    if first_line.startswith(f"<!-- {TRANSITION_NOTICE_MARKER_PREFIX} "):
        return "markerized_transition_notice"
    normalized = body.lower()
    if "**review reminder**" in normalized and (
        "transition period" in normalized
        or "transitioned from producer to observer" in normalized
        or "if no action is taken" in normalized
    ):
        return "legacy_unmarked_warning"
    if "**transition period ended**" in normalized:
        return "legacy_unmarked_transition_notice"
    if "review reminder" in normalized and "github actions" in normalized:
        return "legacy_actions_warning_or_reminder"
    return None


def classify_reviewer_reminder_comment(comment: dict) -> ReminderCommentRecord | None:
    if not isinstance(comment, dict):
        return None
    user = comment.get("user")
    author = user.get("login") if isinstance(user, dict) else None
    created_at = comment.get("created_at")
    body = comment.get("body")
    comment_id = comment.get("id")
    if not isinstance(author, str) or not isinstance(created_at, str) or not isinstance(body, str):
        return None
    if author.lower() not in {value.lower() for value in _REMINDER_AUTHORS}:
        return None
    first_line = _first_line(body)
    matched_shape = _matched_shape(first_line, body)
    if matched_shape is None:
        return None
    return ReminderCommentRecord(
        comment_id=comment_id if isinstance(comment_id, (int, str)) else "",
        author_login=author,
        created_at=created_at,
        body_first_line=first_line,
        matched_shape=matched_shape,
        url=comment.get("html_url") if isinstance(comment.get("html_url"), str) else None,
    )


def scan_reviewer_reminder_comments(comments: list[dict]) -> ReminderCommentScan:
    if not isinstance(comments, list):
        return ReminderCommentScan(records=(), baseline_count=0, baseline_latest_created_at=None, scan_status="blocked_invalid_comment_payload")
    records = tuple(record for comment in comments if (record := classify_reviewer_reminder_comment(comment)) is not None)
    sorted_records = _sort_records(records)
    latest = sorted_records[-1].created_at if sorted_records else None
    return ReminderCommentScan(
        records=sorted_records,
        baseline_count=len(sorted_records),
        baseline_latest_created_at=latest,
        scan_status="pass",
    )


def diff_reviewer_reminder_scans(before: ReminderCommentScan, after: ReminderCommentScan) -> ReminderCommentDiff:
    if before.scan_status != "pass":
        return ReminderCommentDiff(before_count=before.baseline_count, after_count=after.baseline_count, new_records=(), diff_status="blocked_before_scan")
    if after.scan_status != "pass":
        return ReminderCommentDiff(before_count=before.baseline_count, after_count=after.baseline_count, new_records=(), diff_status="blocked_after_scan")
    before_identity = {(record.comment_id, record.created_at, record.matched_shape) for record in before.records}
    new_records = tuple(
        record
        for record in after.records
        if (record.comment_id, record.created_at, record.matched_shape) not in before_identity
    )
    return ReminderCommentDiff(
        before_count=before.baseline_count,
        after_count=after.baseline_count,
        new_records=_sort_records(new_records),
        diff_status="pass",
    )
