"""Live read helpers for deferred reconcile flows."""

from __future__ import annotations

from dataclasses import dataclass

from .timestamps import normalize_iso8601_utc_string


class ReconcileReadError(RuntimeError):
    def __init__(self, message: str, *, failure_kind: str | None = None):
        super().__init__(message)
        self.failure_kind = failure_kind


@dataclass(frozen=True)
class LivePrReplayContext:
    issue_author: str
    issue_labels: tuple[str, ...]


@dataclass(frozen=True)
class LiveCommentReplayContext:
    comment_author: str
    comment_user_type: str
    comment_sender_type: str | None
    comment_installation_id: str | None
    comment_performed_via_github_app: bool | None
    comment_sender_type_available: bool = False
    comment_installation_id_available: bool = False
    comment_performed_via_github_app_available: bool = False


@dataclass(frozen=True)
class DismissalTimeResolution:
    timestamp: str | None
    source: str | None = None
    reason: str | None = None
    failure_kind: str | None = None

    @property
    def exact(self) -> bool:
        return self.timestamp is not None


def _valid_exact_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    timestamp = value.strip()
    if "T" not in timestamp:
        return None
    return normalize_iso8601_utc_string(timestamp)


def _dismissed_review_source_time(payload: dict | None) -> DismissalTimeResolution | None:
    if not isinstance(payload, dict):
        return None
    if "source_dismissed_at" not in payload:
        return None
    value = payload.get("source_dismissed_at")
    if not isinstance(value, str) or not value.strip():
        return None
    timestamp = _valid_exact_timestamp(value)
    if timestamp is None:
        return DismissalTimeResolution(
            None,
            reason="payload_invalid_source_dismissed_at",
            failure_kind="invalid_payload",
        )
    return DismissalTimeResolution(timestamp, source="payload")


def read_review_dismissal_timeline_events(
    bot,
    pr_number: int,
) -> tuple[list[dict] | None, str | None]:
    events: list[dict] = []
    page = 1
    while True:
        endpoint = f"issues/{pr_number}/timeline?per_page=100&page={page}"
        try:
            response = bot.github_api_request("GET", endpoint, retry_policy="idempotent_read")
        except SystemExit:
            payload = bot.github_api("GET", endpoint)
            if not isinstance(payload, list):
                return None, "unavailable"
            page_events = payload
        else:
            if not response.ok:
                return None, response.failure_kind or "unavailable"
            if not isinstance(response.payload, list):
                return None, "invalid_payload"
            page_events = response.payload
        events.extend(event for event in page_events if isinstance(event, dict))
        if len(page_events) < 100:
            return events, None
        page += 1


def resolve_review_dismissal_time(
    bot,
    pr_number: int,
    review_id: int,
    payload: dict,
) -> DismissalTimeResolution:
    payload_time = _dismissed_review_source_time(payload)
    if payload_time is not None:
        return payload_time
    events, failure_kind = read_review_dismissal_timeline_events(bot, pr_number)
    if events is None:
        return DismissalTimeResolution(
            None,
            reason="timeline_unavailable",
            failure_kind=failure_kind,
        )
    matching_times: list[str] = []
    for event in events:
        if event.get("event") != "review_dismissed":
            continue
        dismissed_review = event.get("dismissed_review")
        if not isinstance(dismissed_review, dict) or dismissed_review.get("review_id") != review_id:
            continue
        created_at = event.get("created_at")
        if not isinstance(created_at, str) or not created_at.strip():
            return DismissalTimeResolution(
                None,
                reason="timeline_event_missing_created_at",
                failure_kind="invalid_payload",
            )
        timestamp = _valid_exact_timestamp(created_at)
        if timestamp is None:
            return DismissalTimeResolution(
                None,
                reason="timeline_event_invalid_created_at",
                failure_kind="invalid_payload",
            )
        matching_times.append(timestamp)
    if len(matching_times) == 1:
        return DismissalTimeResolution(matching_times[0], source="timeline")
    if len(matching_times) > 1:
        return DismissalTimeResolution(
            None,
            reason="ambiguous_timeline_dismissal_events",
            failure_kind="invalid_payload",
        )
    return DismissalTimeResolution(
        None,
        reason="timeline_dismissal_event_not_found",
        failure_kind="not_found",
    )


def read_reconcile_object(bot, endpoint: str, *, label: str) -> dict:
    try:
        response = bot.github_api_request("GET", endpoint, retry_policy="idempotent_read")
    except SystemExit:
        payload = bot.github_api("GET", endpoint)
        if not isinstance(payload, dict):
            raise ReconcileReadError(f"{label} unavailable", failure_kind="unavailable")
        return payload
    if not response.ok:
        failure_kind = response.failure_kind
        if failure_kind == "not_found":
            raise ReconcileReadError(f"{label} not found", failure_kind=failure_kind)
        raise ReconcileReadError(f"{label} unavailable", failure_kind=failure_kind)
    if not isinstance(response.payload, dict):
        raise ReconcileReadError(f"{label} payload invalid", failure_kind="invalid_payload")
    return response.payload


def read_optional_reconcile_object(bot, endpoint: str, *, label: str) -> dict | None:
    try:
        return read_reconcile_object(bot, endpoint, label=label)
    except ReconcileReadError as exc:
        if exc.failure_kind == "not_found":
            return None
        raise


def read_reconcile_reviews(bot, issue_number: int) -> list[dict]:
    reviews = bot.github.get_pull_request_reviews(issue_number)
    if reviews is None:
        raise ReconcileReadError(f"live reviews for PR #{issue_number} unavailable", failure_kind="unavailable")
    if not isinstance(reviews, list):
        raise ReconcileReadError(f"live reviews for PR #{issue_number} payload invalid", failure_kind="invalid_payload")
    return reviews


def read_live_pr_replay_context(bot, pr_number: int) -> LivePrReplayContext:
    pull_request = read_reconcile_object(bot, f"pulls/{pr_number}", label=f"live PR #{pr_number} for reconcile context")
    author = pull_request.get("user")
    if not isinstance(author, dict):
        raise RuntimeError(f"Live PR #{pr_number} is missing author metadata")
    author_login = author.get("login")
    if not isinstance(author_login, str) or not author_login.strip():
        raise RuntimeError(f"Live PR #{pr_number} is missing a valid author login")
    labels = pull_request.get("labels")
    if labels is None:
        labels = []
    if not isinstance(labels, list):
        raise RuntimeError(f"Live PR #{pr_number} labels are malformed")
    label_names: list[str] = []
    for label in labels:
        if not isinstance(label, dict):
            raise RuntimeError(f"Live PR #{pr_number} contains malformed label metadata")
        name = label.get("name")
        if not isinstance(name, str):
            raise RuntimeError(f"Live PR #{pr_number} contains a label without a valid name")
        label_names.append(name)
    return LivePrReplayContext(issue_author=author_login, issue_labels=tuple(label_names))


def read_live_comment_replay_context(live_comment: dict, payload: dict) -> LiveCommentReplayContext:
    user = live_comment.get("user")
    if not isinstance(user, dict):
        raise RuntimeError("Live deferred comment user metadata is unavailable")
    comment_author = user.get("login") or payload.get("actor_login") or ""
    if not isinstance(comment_author, str) or not comment_author.strip():
        raise RuntimeError("Live deferred comment author login is unavailable")
    comment_user_type = user.get("type")
    if not isinstance(comment_user_type, str) or not comment_user_type.strip():
        raise RuntimeError("Live deferred comment user type is unavailable")
    sender = live_comment.get("sender")
    comment_sender_type = None
    comment_sender_type_available = False
    if isinstance(sender, dict):
        sender_type = sender.get("type")
        if isinstance(sender_type, str) and sender_type.strip():
            comment_sender_type = sender_type.strip()
            comment_sender_type_available = True
    installation = live_comment.get("installation")
    comment_installation_id = None
    comment_installation_id_available = False
    if isinstance(installation, dict):
        installation_id = installation.get("id")
        if installation_id is not None and str(installation_id).strip():
            try:
                if int(installation_id) > 0:
                    comment_installation_id = str(installation_id).strip()
                    comment_installation_id_available = True
            except (TypeError, ValueError):
                pass
    performed_via_app_available = False
    performed_via_app = live_comment.get("performed_via_github_app")
    comment_performed_via_github_app = None
    if "performed_via_github_app" in live_comment:
        if isinstance(performed_via_app, bool):
            comment_performed_via_github_app = performed_via_app
            performed_via_app_available = True
        elif isinstance(performed_via_app, dict):
            app_id = performed_via_app.get("id")
            if app_id is not None and str(app_id).strip():
                try:
                    comment_performed_via_github_app = int(app_id) > 0
                    performed_via_app_available = True
                except (TypeError, ValueError):
                    pass
        elif performed_via_app is None:
            comment_performed_via_github_app = False
            performed_via_app_available = True
    return LiveCommentReplayContext(
        comment_author=comment_author,
        comment_user_type=comment_user_type,
        comment_sender_type=comment_sender_type,
        comment_installation_id=comment_installation_id,
        comment_performed_via_github_app=comment_performed_via_github_app,
        comment_sender_type_available=comment_sender_type_available,
        comment_installation_id_available=comment_installation_id_available,
        comment_performed_via_github_app_available=performed_via_app_available,
    )
