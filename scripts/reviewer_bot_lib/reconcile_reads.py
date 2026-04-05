"""Live read helpers for deferred reconcile flows."""

from __future__ import annotations

from dataclasses import dataclass


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
    comment_author_association: str
    comment_sender_type: str
    comment_installation_id: str
    comment_performed_via_github_app: bool


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
    author_association = live_comment.get("author_association")
    if not isinstance(author_association, str) or not author_association.strip():
        raise RuntimeError("Live deferred comment author association is unavailable")
    return LiveCommentReplayContext(
        comment_author=comment_author,
        comment_user_type=comment_user_type,
        comment_author_association=author_association,
        comment_sender_type=comment_user_type,
        comment_installation_id="",
        comment_performed_via_github_app=bool(live_comment.get("performed_via_github_app")),
    )
