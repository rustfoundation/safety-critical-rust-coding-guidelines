"""Reviewer-response derivation owner.

Future changes that belong here:
- reviewer-response derivation from stored review state plus already-fetched live PR inputs
- contributor handoff and stale-review response decisions

Future changes that do not belong here:
- label writes, issue writes, or projection application
- mandatory approver escalation

Old module no longer preferred for these reviewer-response decision changes:
- scripts/reviewer_bot_lib/reviews.py
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from . import live_review_support, reviewer_review_helpers

_UNSET = object()
_ASSIGNMENT_GUIDANCE_AUTHORS = {"github-actions", "github-actions[bot]", "guidelines-bot"}
_FAIL_CLOSED_REVIEWER_ACTIVITY_GAP_REASONS = frozenset(
    {
        "observer_failed",
        "observer_cancelled",
        "observer_run_missing",
        "observer_state_unknown",
        "artifact_missing",
        "artifact_invalid",
        "artifact_expired",
        "reconcile_failed_closed",
    }
)
_REVIEWER_ACTIVITY_GAP_KINDS = frozenset(
    {
        "issue_comment:created",
        "pull_request_review:submitted",
        "pull_request_review_comment:created",
    }
)


@dataclass(frozen=True)
class ReviewCycleScope:
    issue_number: int | None
    reviewer: str | None
    head_sha: str | None
    cycle_key: str | None
    scope_key: str | None
    scope_basis: str | None
    anchor_timestamp: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "reviewer": self.reviewer,
            "head_sha": self.head_sha,
            "cycle_key": self.cycle_key,
            "scope_key": self.scope_key,
            "scope_basis": self.scope_basis,
            "anchor_timestamp": self.anchor_timestamp,
        }


@dataclass(frozen=True)
class ReviewerResponseDecision:
    response_state: str
    reason: str | None
    suppression_reason: str | None
    scope: ReviewCycleScope | None
    current_head_sha: str | None
    anchor_timestamp: str | None
    reviewer_authority_outcome: str | None
    latest_reviewer_activity_kind: str | None
    latest_reviewer_activity_timestamp: str | None
    latest_contributor_handoff_timestamp: str | None
    suppresses_overdue_reminder: bool
    suppresses_reassignment_followup: bool
    completion_state: str | None
    write_approval_authority: dict[str, object] | None

    def to_output(self) -> dict[str, object]:
        return {
            "response_state": self.response_state,
            "reason": self.reason,
            "suppression_reason": self.suppression_reason,
            "scope": self.scope.to_output() if self.scope is not None else None,
            "current_head_sha": self.current_head_sha,
            "anchor_timestamp": self.anchor_timestamp,
            "reviewer_authority_outcome": self.reviewer_authority_outcome,
            "latest_reviewer_activity_kind": self.latest_reviewer_activity_kind,
            "latest_reviewer_activity_timestamp": self.latest_reviewer_activity_timestamp,
            "latest_contributor_handoff_timestamp": self.latest_contributor_handoff_timestamp,
            "suppresses_overdue_reminder": self.suppresses_overdue_reminder,
            "suppresses_reassignment_followup": self.suppresses_reassignment_followup,
            "completion_state": self.completion_state,
            "write_approval_authority": self.write_approval_authority,
        }


@dataclass(frozen=True)
class ReviewerActivityRecord:
    kind: str
    actor: str | None
    timestamp: str | None
    source_event_key: str | None
    reviewed_head_sha: str | None
    activity_scope: str
    payload: dict[str, object]

    def to_output(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "actor": self.actor,
            "timestamp": self.timestamp,
            "source_event_key": self.source_event_key,
            "reviewed_head_sha": self.reviewed_head_sha,
            "activity_scope": self.activity_scope,
            "payload": dict(self.payload),
        }


def derive_review_cycle_scope(
    payload: dict[str, object],
    *,
    issue_number: int | None = None,
    reviewer: str | None = None,
) -> ReviewCycleScope | None:
    scope_key = payload.get("current_scope_key") or payload.get("scope_key")
    if not isinstance(scope_key, str) or not scope_key.strip():
        return None
    return ReviewCycleScope(
        issue_number=issue_number,
        reviewer=reviewer,
        head_sha=payload.get("current_head_sha") if isinstance(payload.get("current_head_sha"), str) else None,
        cycle_key=payload.get("cycle_key") if isinstance(payload.get("cycle_key"), str) else None,
        scope_key=scope_key,
        scope_basis=payload.get("current_scope_basis") if isinstance(payload.get("current_scope_basis"), str) else None,
        anchor_timestamp=payload.get("anchor_timestamp") if isinstance(payload.get("anchor_timestamp"), str) else None,
    )


def to_reviewer_response_decision(payload: dict[str, object]) -> ReviewerResponseDecision:
    response_state = str(payload.get("response_state") or payload.get("state") or "projection_failed")
    scope = derive_review_cycle_scope(
        payload,
        issue_number=payload.get("issue_number") if isinstance(payload.get("issue_number"), int) else None,
        reviewer=payload.get("current_reviewer") if isinstance(payload.get("current_reviewer"), str) else None,
    )
    return ReviewerResponseDecision(
        response_state=response_state,
        reason=payload.get("reason") if isinstance(payload.get("reason"), str) else None,
        suppression_reason=payload.get("suppression_reason") if isinstance(payload.get("suppression_reason"), str) else None,
        scope=scope,
        current_head_sha=payload.get("current_head_sha") if isinstance(payload.get("current_head_sha"), str) else None,
        anchor_timestamp=payload.get("anchor_timestamp") if isinstance(payload.get("anchor_timestamp"), str) else None,
        reviewer_authority_outcome=payload.get("reviewer_authority_outcome") if isinstance(payload.get("reviewer_authority_outcome"), str) else None,
        latest_reviewer_activity_kind=payload.get("latest_reviewer_activity_kind") if isinstance(payload.get("latest_reviewer_activity_kind"), str) else None,
        latest_reviewer_activity_timestamp=payload.get("latest_reviewer_activity_timestamp") if isinstance(payload.get("latest_reviewer_activity_timestamp"), str) else None,
        latest_contributor_handoff_timestamp=payload.get("latest_contributor_handoff_timestamp") if isinstance(payload.get("latest_contributor_handoff_timestamp"), str) else None,
        suppresses_overdue_reminder=bool(payload.get("suppresses_overdue_reminder", response_state != "awaiting_reviewer_response")),
        suppresses_reassignment_followup=bool(payload.get("suppresses_reassignment_followup", response_state in {"done", "closed", "untracked"})),
        completion_state=payload.get("completion_state") if isinstance(payload.get("completion_state"), str) else None,
        write_approval_authority=payload.get("write_approval_authority") if isinstance(payload.get("write_approval_authority"), dict) else None,
    )


def apply_reminder_cadence_overlay(response: ReviewerResponseDecision, cadence) -> ReviewerResponseDecision:
    if cadence is None or not getattr(cadence, "must_project_reassignment_needed", False):
        return response
    if response.response_state != "awaiting_reviewer_response":
        return response
    reason = getattr(cadence, "exhaustion_reason", None) or "legacy_duplicate_reminders_exhausted"
    scope = (
        replace(response.scope, scope_basis="reminder_cadence_exhausted")
        if response.scope is not None
        else None
    )
    return ReviewerResponseDecision(
        response_state="reviewer_reassignment_needed",
        reason=reason,
        suppression_reason=reason,
        scope=scope,
        current_head_sha=response.current_head_sha,
        anchor_timestamp=response.anchor_timestamp,
        reviewer_authority_outcome=response.reviewer_authority_outcome,
        latest_reviewer_activity_kind=response.latest_reviewer_activity_kind,
        latest_reviewer_activity_timestamp=response.latest_reviewer_activity_timestamp,
        latest_contributor_handoff_timestamp=response.latest_contributor_handoff_timestamp,
        suppresses_overdue_reminder=True,
        suppresses_reassignment_followup=True,
        completion_state=response.completion_state,
        write_approval_authority=response.write_approval_authority,
    )


def classify_reviewer_activity_scope(activity: ReviewerActivityRecord, *, current_head_sha: str | None) -> str:
    if activity.activity_scope in {"current_head", "stale_head", "issue_thread", "diagnostic_only", "unknown"}:
        return activity.activity_scope
    if activity.reviewed_head_sha is None:
        return "issue_thread" if activity.kind == "reviewer_comment" else "diagnostic_only"
    if isinstance(current_head_sha, str) and activity.reviewed_head_sha == current_head_sha:
        return "current_head"
    return "stale_head"


def _record_timestamp(record: dict | None, *, parse_timestamp) -> datetime | None:
    if not isinstance(record, dict):
        return None
    return parse_timestamp(record.get("timestamp"))


def _compare_cross_channel_conversation(contributor: dict | None, reviewer: dict | None, *, parse_timestamp) -> int:
    contributor_time = _record_timestamp(contributor, parse_timestamp=parse_timestamp) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    reviewer_time = _record_timestamp(reviewer, parse_timestamp=parse_timestamp) or datetime.min.replace(
        tzinfo=timezone.utc
    )
    contributor_key = str((contributor or {}).get("semantic_key", ""))
    reviewer_key = str((reviewer or {}).get("semantic_key", ""))
    if (contributor_time, contributor_key) == (reviewer_time, reviewer_key):
        return 0
    if contributor_time > reviewer_time:
        return 1
    if contributor_time < reviewer_time:
        return -1
    if contributor_key >= reviewer_key:
        return 1
    return -1


def _initial_reviewer_anchor(review_data: dict) -> str | None:
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        value = review_data.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _initial_cycle_boundary(review_data: dict) -> tuple[str | None, str | None]:
    for field in ("active_cycle_started_at", "cycle_started_at", "assigned_at"):
        value = review_data.get(field)
        if isinstance(value, str) and value:
            return field, value
    return None, None


def _claim_assignment_guidance_timestamp(bot, issue_number: int, current_reviewer: str | None) -> str | None:
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return None
    expected_first_line = f"👋 Hey @{current_reviewer}! You've been assigned to review this coding guideline PR."
    first_match: tuple[datetime, str] | None = None
    page = 1
    while True:
        try:
            response = bot.github.list_issue_comments_result(issue_number, page=page)
        except (AssertionError, RuntimeError):
            return None
        if not response.ok or not isinstance(response.payload, list):
            return None
        for comment in response.payload:
            if not isinstance(comment, dict):
                continue
            user = comment.get("user")
            login = user.get("login") if isinstance(user, dict) else None
            created_at = comment.get("created_at")
            body = comment.get("body")
            if not isinstance(login, str) or not isinstance(created_at, str) or not isinstance(body, str):
                continue
            if login.lower() not in _ASSIGNMENT_GUIDANCE_AUTHORS:
                continue
            lines = body.splitlines()
            first_line = lines[0].strip() if lines else ""
            if first_line != expected_first_line:
                continue
            created_dt = live_review_support.parse_github_timestamp(created_at)
            if created_dt is None:
                continue
            if first_match is None or created_dt < first_match[0]:
                first_match = (created_dt, created_at)
        if len(response.payload) < 100:
            break
        page += 1
    return first_match[1] if first_match is not None else None


def _alternate_current_head_cycle_boundary(bot, issue_number: int, review_data: dict, issue_snapshot: dict | None) -> str | None:
    if not isinstance(issue_snapshot, dict) or not isinstance(issue_snapshot.get("pull_request"), dict):
        return None
    if review_data.get("assignment_method") != "claim":
        return None
    for field in ("active_cycle_started_at", "cycle_started_at"):
        value = review_data.get(field)
        if isinstance(value, str) and value:
            return None
    return _claim_assignment_guidance_timestamp(bot, issue_number, review_data.get("current_reviewer"))


def _scope_basis_and_anchor(review_data: dict, contributor_handoff: dict | None) -> tuple[str | None, str | None]:
    if isinstance(contributor_handoff, dict):
        semantic_key = str(contributor_handoff.get("semantic_key", ""))
        basis = "contributor_revision" if semantic_key.startswith("pull_request_") else "contributor_comment"
        anchor = contributor_handoff.get("timestamp")
        return basis, anchor if isinstance(anchor, str) and anchor else None
    return _initial_cycle_boundary(review_data)


def _scope_value(value: str | None) -> str:
    return value if isinstance(value, str) and value else "none"


def _build_current_scope_key(
    current_reviewer: str | None,
    current_head: str | None,
    cycle_boundary: str | None,
    anchor_timestamp: str | None,
) -> str | None:
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return None
    return (
        f"reviewer={current_reviewer}|head={_scope_value(current_head)}|"
        f"cycle={_scope_value(cycle_boundary)}|anchor={_scope_value(anchor_timestamp)}"
    )


def _gap_source_kind(gap: dict) -> str | None:
    source_event_kind = gap.get("source_event_kind")
    if isinstance(source_event_kind, str) and source_event_kind.strip():
        return source_event_kind
    source_event_key = gap.get("source_event_key")
    if not isinstance(source_event_key, str):
        return None
    if source_event_key.startswith("issue_comment:"):
        return "issue_comment:created"
    if source_event_key.startswith("pull_request_review_comment:"):
        return "pull_request_review_comment:created"
    if source_event_key.startswith("pull_request_review:"):
        return "pull_request_review:submitted"
    return None


def _gap_event_timestamp(gap: dict):
    return live_review_support.parse_github_timestamp(gap.get("source_event_created_at"))


def _visible_review_commit_id(gap: dict) -> str | None:
    diagnostic = gap.get("visible_review_diagnostic")
    payload = diagnostic.get("payload") if isinstance(diagnostic, dict) else None
    commit_id = payload.get("commit_id") if isinstance(payload, dict) else None
    if isinstance(commit_id, str) and commit_id.strip():
        return commit_id
    source_commit_id = gap.get("source_commit_id")
    if isinstance(source_commit_id, str) and source_commit_id.strip():
        return source_commit_id
    comment = gap.get("comment")
    comment_commit_id = None
    if isinstance(comment, dict):
        comment_commit_id = comment.get("commit_id") or comment.get("original_commit_id")
    return comment_commit_id if isinstance(comment_commit_id, str) and comment_commit_id.strip() else None


def _visible_activity_author(gap: dict) -> str | None:
    diagnostic = gap.get("visible_review_diagnostic")
    payload = diagnostic.get("payload") if isinstance(diagnostic, dict) else None
    author = payload.get("author") if isinstance(payload, dict) else None
    if isinstance(author, str) and author.strip():
        return author
    source_actor = gap.get("source_actor_login")
    if isinstance(source_actor, str) and source_actor.strip():
        return source_actor
    actor = gap.get("actor")
    if isinstance(actor, str) and actor.strip():
        return actor
    comment = gap.get("comment")
    user = comment.get("user") if isinstance(comment, dict) else None
    login = user.get("login") if isinstance(user, dict) else None
    return login if isinstance(login, str) and login.strip() else None


def has_fail_closed_reviewer_activity_for_current_scope(
    review_data: dict,
    fail_closed_gaps,
    *,
    anchor_timestamp: str | None = None,
    current_head_sha: str | None = None,
) -> bool:
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return False
    floor = live_review_support.parse_github_timestamp(anchor_timestamp)
    if floor is None:
        _, cycle_boundary = _initial_cycle_boundary(review_data)
        floor = live_review_support.parse_github_timestamp(cycle_boundary)
    for gap in fail_closed_gaps:
        if not isinstance(gap, dict):
            continue
        if gap.get("operator_action_required") is not True:
            continue
        if gap.get("reason") not in _FAIL_CLOSED_REVIEWER_ACTIVITY_GAP_REASONS:
            continue
        source_kind = _gap_source_kind(gap)
        if source_kind not in _REVIEWER_ACTIVITY_GAP_KINDS:
            continue
        event_timestamp = _gap_event_timestamp(gap)
        if event_timestamp is None:
            continue
        if floor is not None and event_timestamp < floor:
            continue
        author = _visible_activity_author(gap)
        if not isinstance(author, str) or author.lower() != current_reviewer.lower():
            continue
        if source_kind in {"pull_request_review:submitted", "pull_request_review_comment:created"}:
            if not isinstance(current_head_sha, str) or not current_head_sha.strip():
                continue
            commit_id = _visible_review_commit_id(gap)
            if commit_id != current_head_sha:
                continue
        return True
    return False


def _current_scope_fields(
    review_data: dict,
    current_reviewer: str | None,
    current_head: str | None,
    contributor_handoff: dict | None,
    *,
    alternate_current_head_approval: bool = False,
    alternate_current_head_cycle_boundary: str | None = None,
) -> dict[str, object]:
    _, cycle_boundary = _initial_cycle_boundary(review_data)
    if alternate_current_head_approval and alternate_current_head_cycle_boundary:
        cycle_boundary = alternate_current_head_cycle_boundary
    if alternate_current_head_approval:
        anchor_timestamp = None
        basis = "alternate_current_head_approval"
    else:
        basis, anchor_timestamp = _scope_basis_and_anchor(review_data, contributor_handoff)
    return {
        "current_scope_basis": basis,
        "current_scope_key": _build_current_scope_key(
            current_reviewer,
            current_head,
            cycle_boundary,
            anchor_timestamp,
        ),
    }


def _decorate_response(
    *,
    state: str,
    reason: str | None,
    scope_fields: dict[str, object],
    **payload,
) -> dict[str, object]:
    legacy = {
        "state": state,
        "response_state": state,
        "reason": reason,
        "suppression_reason": reason,
        **scope_fields,
        **payload,
    }
    decision = to_reviewer_response_decision(legacy)
    return {
        **legacy,
        **decision.to_output(),
        "state": decision.response_state,
        "current_scope_key": scope_fields.get("current_scope_key"),
        "current_scope_basis": scope_fields.get("current_scope_basis"),
    }


def _write_approval_authority_payload(write_approval: object) -> dict[str, object] | None:
    if not isinstance(write_approval, dict):
        return None
    authority = write_approval.get("authority_decision")
    return dict(authority) if isinstance(authority, dict) else None


def _record_for_current_reviewer(record: dict | None | object, current_reviewer: str) -> dict | None:
    if not isinstance(record, dict):
        return None
    actor = record.get("actor")
    if not isinstance(actor, str) or not actor.strip():
        return record
    if actor.lower() != current_reviewer.lower():
        return None
    return record


def _current_cycle_reviewer_handoff_record(
    review_data: dict,
    current_reviewer: str,
    current_head: str | None,
    *,
    issue_is_pull_request: bool,
) -> dict | None:
    handoff = review_data.get("current_cycle_reviewer_handoff")
    if not isinstance(handoff, dict):
        return None
    if handoff.get("command_name") != "feedback":
        return None
    actor = handoff.get("actor")
    timestamp = handoff.get("timestamp")
    source_event_key = handoff.get("source_event_key")
    if not isinstance(actor, str) or actor.lower() != current_reviewer.lower():
        return None
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    if not isinstance(source_event_key, str) or not source_event_key.strip():
        return None
    handoff_time = live_review_support.parse_github_timestamp(timestamp)
    if handoff_time is None:
        return None
    _, cycle_boundary = _initial_cycle_boundary(review_data)
    cycle_boundary_time = live_review_support.parse_github_timestamp(cycle_boundary)
    if cycle_boundary_time is not None and handoff_time < cycle_boundary_time:
        return None
    reviewed_head_sha = handoff.get("reviewed_head_sha")
    if issue_is_pull_request:
        if not isinstance(reviewed_head_sha, str) or reviewed_head_sha != current_head:
            return None
    elif reviewed_head_sha is not None:
        return None
    return {
        "semantic_key": source_event_key,
        "timestamp": timestamp,
        "actor": actor,
        "reviewed_head_sha": reviewed_head_sha,
        "source_precedence": 1,
        "payload": {"command_name": "feedback"},
    }


def _contributor_revision_handoff_record(review_data: dict, current_head: str | None, reviewer_review: dict | None) -> dict | None:
    contributor_revision = review_data.get("contributor_revision", {}).get("accepted")
    if not isinstance(contributor_revision, dict):
        return None
    revision_head = contributor_revision.get("reviewed_head_sha")
    if not isinstance(revision_head, str) or not isinstance(current_head, str):
        return None
    if revision_head != current_head:
        return None
    reviewer_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if isinstance(reviewer_head, str) and reviewer_head == current_head:
        return None
    return contributor_revision


def _current_head_approval_authors(
    review_data: dict,
    current_head: str | None,
    reviews: list[dict] | None,
    *,
    parse_timestamp,
) -> tuple[str, ...]:
    if not isinstance(current_head, str) or not current_head.strip() or not isinstance(reviews, list):
        return ()
    boundary = live_review_support.get_current_cycle_boundary(review_data, parse_timestamp=parse_timestamp)
    if boundary is None:
        return ()
    normalized_reviews = live_review_support.normalize_reviews_with_parsed_timestamps(
        reviews,
        parse_timestamp=live_review_support.parse_github_timestamp,
    )
    survivors = live_review_support.filter_current_head_reviews_for_cycle(
        normalized_reviews,
        boundary=boundary,
        current_head=current_head,
    )
    approvals = []
    for review in survivors.values():
        if str(review.get("state", "")).upper() != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if isinstance(author, str) and author.strip():
            approvals.append(author)
    approvals.sort(key=str.lower)
    return tuple(approvals)


def derive_reviewer_response_state(
    review_data: dict,
    *,
    issue_is_pull_request: bool,
    current_head: str | None = None,
    reviewer_comment: dict | None | object = _UNSET,
    reviewer_review: dict | None | object = _UNSET,
    contributor_comment: dict | None | object = _UNSET,
    had_reviewer_review: bool = False,
    approval_result: dict[str, object] | None = None,
    current_head_approval_authors: tuple[str, ...] | None = None,
    stored_reviewer_review: dict | None | object = _UNSET,
    alternate_current_head_cycle_boundary: str | None = None,
) -> dict[str, object]:
    current_reviewer = review_data.get("current_reviewer")
    if not isinstance(current_reviewer, str) or not current_reviewer.strip():
        return _decorate_response(
            state="untracked",
            reason="no_current_reviewer",
            scope_fields={"current_scope_key": None, "current_scope_basis": None},
        )

    if reviewer_comment is _UNSET:
        reviewer_comment = review_data.get("reviewer_comment", {}).get("accepted")
    if reviewer_review is _UNSET:
        reviewer_review = review_data.get("reviewer_review", {}).get("accepted")
    if stored_reviewer_review is _UNSET:
        stored_reviewer_review = reviewer_review
    if contributor_comment is _UNSET:
        contributor_comment = review_data.get("contributor_comment", {}).get("accepted")

    if not issue_is_pull_request:
        reviewer_comment = _record_for_current_reviewer(reviewer_comment, current_reviewer)
        reviewer_review = _record_for_current_reviewer(reviewer_review, current_reviewer)
        latest_reviewer_response = reviewer_comment
        if reviewer_review_helpers.compare_records(
            reviewer_review,
            latest_reviewer_response,
            parse_timestamp=live_review_support.parse_github_timestamp,
        ) > 0:
            latest_reviewer_response = reviewer_review
        reviewer_handoff = _current_cycle_reviewer_handoff_record(
            review_data,
            current_reviewer,
            None,
            issue_is_pull_request=False,
        )
        if _compare_cross_channel_conversation(
            contributor_comment,
            reviewer_handoff,
            parse_timestamp=live_review_support.parse_github_timestamp,
        ) > 0:
            reviewer_handoff = None
        if reviewer_review_helpers.compare_records(
            reviewer_handoff,
            latest_reviewer_response,
            parse_timestamp=live_review_support.parse_github_timestamp,
        ) > 0:
            latest_reviewer_response = reviewer_handoff
        if reviewer_handoff is not None and latest_reviewer_response is reviewer_handoff:
            if _compare_cross_channel_conversation(
                contributor_comment,
                reviewer_handoff,
                parse_timestamp=live_review_support.parse_github_timestamp,
            ) > 0:
                return _decorate_response(
                    state="awaiting_reviewer_response",
                    reason="contributor_comment_newer",
                    scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
                    anchor_timestamp=contributor_comment.get("timestamp") if isinstance(contributor_comment, dict) else None,
                    reviewer_comment=reviewer_comment,
                    reviewer_review=reviewer_review,
                    current_cycle_reviewer_handoff=reviewer_handoff,
                    contributor_comment=contributor_comment,
                    contributor_handoff=contributor_comment,
                )
            return _decorate_response(
                state="awaiting_contributor_response",
                reason="completion_missing",
                scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
                anchor_timestamp=reviewer_handoff.get("timestamp"),
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_comment,
            )
        completion = review_data.get("current_cycle_completion")
        if isinstance(completion, dict) and completion.get("completed"):
            return _decorate_response(
                state="done",
                reason=None,
                scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
                anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_comment,
            )
        if review_data.get("review_completed_at"):
            return _decorate_response(
                state="done",
                reason=None,
                scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
                anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_comment,
            )
        if not latest_reviewer_response:
            return _decorate_response(
                state="awaiting_reviewer_response",
                reason="no_reviewer_activity",
                scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
                anchor_timestamp=_initial_reviewer_anchor(review_data),
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_comment,
            )
        if _compare_cross_channel_conversation(
            contributor_comment,
            latest_reviewer_response,
            parse_timestamp=live_review_support.parse_github_timestamp,
        ) > 0:
            return _decorate_response(
                state="awaiting_reviewer_response",
                reason="contributor_comment_newer",
                scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
                anchor_timestamp=contributor_comment.get("timestamp") if isinstance(contributor_comment, dict) else None,
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_comment,
            )
        return _decorate_response(
            state="awaiting_contributor_response",
            reason="completion_missing",
            scope_fields=_current_scope_fields(review_data, current_reviewer, None, contributor_comment),
            anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_comment,
        )

    if not isinstance(current_head, str) or not current_head.strip():
        return _decorate_response(
            state="projection_failed",
            reason="pull_request_head_unavailable",
            scope_fields={"current_scope_key": None, "current_scope_basis": None},
        )
    # Plain PR issue/review comments are diagnostic-only in v65. Explicit
    # command handoff is represented separately by current_cycle_reviewer_handoff.
    reviewer_comment = None

    reviewer_handoff = _current_cycle_reviewer_handoff_record(
        review_data,
        current_reviewer,
        current_head,
        issue_is_pull_request=True,
    )

    contributor_handoff = contributor_comment
    contributor_revision = _contributor_revision_handoff_record(
        review_data,
        current_head,
        reviewer_review if isinstance(reviewer_review, dict) else None,
    )
    if reviewer_review_helpers.compare_records(
        contributor_revision,
        contributor_handoff,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        contributor_handoff = contributor_revision
    if _compare_cross_channel_conversation(
        contributor_handoff,
        reviewer_handoff,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        reviewer_handoff = None

    if not reviewer_comment and not reviewer_review and not reviewer_handoff:
        if not had_reviewer_review:
            return _decorate_response(
                state="awaiting_reviewer_response",
                reason="no_reviewer_activity",
                scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, None),
                anchor_timestamp=_initial_reviewer_anchor(review_data),
                current_head_sha=current_head,
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=None,
            )

    latest_reviewer_response = reviewer_comment
    if reviewer_review_helpers.compare_records(
        reviewer_review,
        latest_reviewer_response,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        latest_reviewer_response = reviewer_review
    if reviewer_review_helpers.compare_records(
        reviewer_handoff,
        latest_reviewer_response,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        latest_reviewer_response = reviewer_handoff

    if _compare_cross_channel_conversation(
        contributor_handoff,
        latest_reviewer_response,
        parse_timestamp=live_review_support.parse_github_timestamp,
    ) > 0:
        reason = "contributor_comment_newer"
        if isinstance(contributor_handoff, dict) and str(contributor_handoff.get("semantic_key", "")).startswith(
            "pull_request_"
        ):
            reason = "contributor_revision_newer"
        return _decorate_response(
            state="awaiting_reviewer_response",
            reason=reason,
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            anchor_timestamp=contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else None,
            current_head_sha=current_head,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_handoff,
        )

    if reviewer_handoff is not None and latest_reviewer_response is reviewer_handoff:
        return _decorate_response(
            state="awaiting_contributor_response",
            reason="reviewer_feedback_handoff",
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            anchor_timestamp=reviewer_handoff.get("timestamp"),
            current_head_sha=current_head,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_handoff,
        )

    approval_authors = tuple(author for author in (current_head_approval_authors or ()) if isinstance(author, str) and author.strip())
    normalized_approval_authors = {author.lower() for author in approval_authors}
    if current_reviewer.lower() in normalized_approval_authors:
        latest_review_head = stored_reviewer_review.get("reviewed_head_sha") if isinstance(stored_reviewer_review, dict) else None
        if not isinstance(latest_review_head, str) or latest_review_head != current_head:
            return _decorate_response(
                state="projection_failed",
                reason="public_current_head_approval_contradiction",
                scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
                anchor_timestamp=contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else _initial_reviewer_anchor(review_data),
                current_head_sha=current_head,
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_handoff,
            )
    del alternate_current_head_cycle_boundary

    latest_review_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    if not isinstance(latest_review_head, str) or latest_review_head != current_head:
        if isinstance(reviewer_comment, dict) or isinstance(reviewer_handoff, dict):
            response_anchor = reviewer_comment if isinstance(reviewer_comment, dict) else reviewer_handoff
            return _decorate_response(
                state="awaiting_contributor_response",
                reason="reviewer_feedback_handoff",
                scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
                anchor_timestamp=response_anchor.get("timestamp") if isinstance(response_anchor.get("timestamp"), str) else None,
                current_head_sha=current_head,
                reviewer_comment=reviewer_comment,
                reviewer_review=reviewer_review,
                current_cycle_reviewer_handoff=reviewer_handoff,
                contributor_comment=contributor_comment,
                contributor_handoff=contributor_handoff,
            )
        return _decorate_response(
            state="awaiting_reviewer_response",
            reason="review_head_stale",
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            anchor_timestamp=contributor_handoff.get("timestamp") if isinstance(contributor_handoff, dict) else _initial_reviewer_anchor(review_data),
            current_head_sha=current_head,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_handoff,
        )

    if not isinstance(approval_result, dict) or not approval_result.get("ok"):
        write_approval_authority = _write_approval_authority_payload(
            approval_result.get("write_approval") if isinstance(approval_result, dict) else None
        )
        return _decorate_response(
            state="projection_failed",
            reason="live_review_state_unknown",
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            write_approval_authority=write_approval_authority,
        )

    completion = approval_result["completion"]
    write_approval = approval_result["write_approval"]
    write_approval_authority = _write_approval_authority_payload(write_approval)
    if not completion.get("completed"):
        return _decorate_response(
            state="awaiting_contributor_response",
            reason="completion_missing",
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            current_head_sha=current_head,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_handoff,
        )
    authority_response_state = write_approval.get("response_state")
    if authority_response_state == "awaiting_contributor_response":
        return _decorate_response(
            state="awaiting_contributor_response",
            reason="assigned_reviewer_review_submitted",
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            current_head_sha=current_head,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_handoff,
            write_approval_authority=write_approval_authority,
        )
    if authority_response_state == "projection_failed":
        authority = write_approval.get("authority_decision")
        reason = "write_approval_authority_unavailable"
        if isinstance(authority, dict) and isinstance(authority.get("diagnostic_reason"), str):
            reason = str(authority["diagnostic_reason"])
        return _decorate_response(
            state="projection_failed",
            reason=reason,
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            write_approval_authority=write_approval_authority,
        )
    if not write_approval.get("has_write_approval"):
        return _decorate_response(
            state="awaiting_write_approval",
            reason="write_approval_missing",
            scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
            anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
            current_head_sha=current_head,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            current_cycle_reviewer_handoff=reviewer_handoff,
            contributor_comment=contributor_comment,
            contributor_handoff=contributor_handoff,
            write_approval_authority=write_approval_authority,
        )
    return _decorate_response(
        state="done",
        reason="write_approval_present",
        scope_fields=_current_scope_fields(review_data, current_reviewer, current_head, contributor_handoff),
        anchor_timestamp=latest_reviewer_response.get("timestamp") if isinstance(latest_reviewer_response, dict) else None,
        current_head_sha=current_head,
        reviewer_comment=reviewer_comment,
        reviewer_review=reviewer_review,
        current_cycle_reviewer_handoff=reviewer_handoff,
        contributor_comment=contributor_comment,
        contributor_handoff=contributor_handoff,
        write_approval_authority=write_approval_authority,
    )


def compute_reviewer_response_state(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    issue_snapshot: dict | None = None,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    if issue_snapshot is None:
        issue_snapshot = bot.github.get_issue_or_pr_snapshot(issue_number)
    if not isinstance(issue_snapshot, dict):
        return _decorate_response(
            state="projection_failed",
            reason="issue_snapshot_unavailable",
            scope_fields={"current_scope_key": None, "current_scope_basis": None},
        )
    is_pr = isinstance(issue_snapshot.get("pull_request"), dict)

    reviewer_comment = review_data.get("reviewer_comment", {}).get("accepted")
    reviewer_review = review_data.get("reviewer_review", {}).get("accepted")
    stored_reviewer_review = reviewer_review
    contributor_comment = review_data.get("contributor_comment", {}).get("accepted")
    had_reviewer_review = isinstance(reviewer_review, dict)
    if is_pr:
        # Plain PR issue/review comments are diagnostic-only in v65. Explicit
        # command handoff is represented separately by current_cycle_reviewer_handoff.
        reviewer_comment = None

    if not is_pr:
        return derive_reviewer_response_state(
            review_data,
            issue_is_pull_request=False,
            reviewer_comment=reviewer_comment,
            reviewer_review=reviewer_review,
            contributor_comment=contributor_comment,
            had_reviewer_review=had_reviewer_review,
        )

    pull_request_result = live_review_support.read_pull_request_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return _decorate_response(
            state="projection_failed",
            reason=str(pull_request_result.get("reason")),
            scope_fields={"current_scope_key": None, "current_scope_basis": None},
        )
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return _decorate_response(
            state="projection_failed",
            reason="pull_request_head_unavailable",
            scope_fields={"current_scope_key": None, "current_scope_basis": None},
        )

    if reviews is None:
        reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews)
        if not reviews_result.get("ok"):
            return _decorate_response(
                state="projection_failed",
                reason=str(reviews_result.get("reason")),
                scope_fields=_current_scope_fields(review_data, review_data.get("current_reviewer"), current_head, None),
            )
        reviews = reviews_result["reviews"]

    if not reviewer_comment and not reviewer_review:
        preferred_live_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )
        if preferred_live_review is not None:
            reviewer_review = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
                preferred_live_review,
                actor=review_data.get("current_reviewer"),
            )

    stored_review_head = reviewer_review.get("reviewed_head_sha") if isinstance(reviewer_review, dict) else None
    refresh_live_review = reviews is not None or reviewer_review is None
    if not refresh_live_review:
        refresh_live_review = not isinstance(stored_review_head, str) or stored_review_head != current_head

    preferred_live_review = None
    if refresh_live_review:
        preferred_live_review = reviewer_review_helpers.get_preferred_current_reviewer_review_for_cycle(
            bot,
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )
    if preferred_live_review is not None:
        reviewer_review = reviewer_review_helpers.build_reviewer_review_record_from_live_review(
            preferred_live_review,
            actor=review_data.get("current_reviewer"),
        )
    elif refresh_live_review:
        reviewer_review = None

    from scripts.reviewer_bot_core import approval_policy

    approval_result = approval_policy.compute_pr_approval_state_result(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    approval_authors = _current_head_approval_authors(
        review_data,
        current_head,
        reviews,
        parse_timestamp=bot.parse_iso8601_timestamp,
    )
    alternate_current_head_cycle_boundary = _alternate_current_head_cycle_boundary(
        bot,
        issue_number,
        review_data,
        issue_snapshot,
    )

    return derive_reviewer_response_state(
        review_data,
        issue_is_pull_request=True,
        current_head=current_head,
        reviewer_comment=reviewer_comment,
        reviewer_review=reviewer_review,
        contributor_comment=contributor_comment,
        had_reviewer_review=had_reviewer_review,
        approval_result=approval_result,
        current_head_approval_authors=approval_authors,
        stored_reviewer_review=stored_reviewer_review,
        alternate_current_head_cycle_boundary=alternate_current_head_cycle_boundary,
    )
