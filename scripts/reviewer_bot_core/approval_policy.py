"""Approval and completion derivation owner.

Future changes that belong here:
- approval/completion derivation from pull-request snapshots, review snapshots, and
  permission observations
- triage-approval derivation from already-fetched review inputs

Future changes that do not belong here:
- reviewer-response derivation
- state mutation, label writes, escalation, or other side effects
- pure projection helper implementations that remain in `reviews_projection.py`

Old module no longer preferred for these derivation changes:
- `scripts/reviewer_bot_lib/reviews.py`
"""

from __future__ import annotations

from dataclasses import dataclass

from . import live_review_support


@dataclass(frozen=True)
class CompletionAuthorityDecision:
    issue_number: int | None
    tracked_reviewer: str | None
    head_sha: str | None
    completion_state: str
    completion_timestamp: str | None
    timestamp_source: str
    source_review_id: int | str | None
    source_review_state: str | None
    non_assigned_review_diagnostic: bool
    can_set_review_completed_at: bool
    diagnostic_reason: str | None

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "tracked_reviewer": self.tracked_reviewer,
            "head_sha": self.head_sha,
            "completion_state": self.completion_state,
            "completion_timestamp": self.completion_timestamp,
            "timestamp_source": self.timestamp_source,
            "source_review_id": self.source_review_id,
            "source_review_state": self.source_review_state,
            "non_assigned_review_diagnostic": self.non_assigned_review_diagnostic,
            "can_set_review_completed_at": self.can_set_review_completed_at,
            "diagnostic_reason": self.diagnostic_reason,
        }


@dataclass(frozen=True)
class WriteApprovalAuthorityDecision:
    issue_number: int | None
    head_sha: str | None
    assigned_reviewer: str | None
    assigned_review_id: int | str | None
    assigned_review_state: str | None
    assigned_round_complete: bool
    write_approval_state: str
    write_approval_source: str
    approving_reviewer: str | None
    approving_review_id: int | str | None
    permission_source: str | None
    dismissal_supersession_status: str
    response_state: str
    diagnostic_reason: str | None
    can_project_final_state: bool

    def to_output(self) -> dict[str, object]:
        return {
            "issue_number": self.issue_number,
            "head_sha": self.head_sha,
            "assigned_reviewer": self.assigned_reviewer,
            "assigned_review_id": self.assigned_review_id,
            "assigned_review_state": self.assigned_review_state,
            "assigned_round_complete": self.assigned_round_complete,
            "write_approval_state": self.write_approval_state,
            "write_approval_source": self.write_approval_source,
            "approving_reviewer": self.approving_reviewer,
            "approving_review_id": self.approving_review_id,
            "permission_source": self.permission_source,
            "dismissal_supersession_status": self.dismissal_supersession_status,
            "response_state": self.response_state,
            "diagnostic_reason": self.diagnostic_reason,
            "can_project_final_state": self.can_project_final_state,
        }


def derive_completion_authority_decision(
    *,
    issue_number: int | None,
    tracked_reviewer: str | None,
    head_sha: str | None,
    review_classification: live_review_support.ReviewFreshnessClassification | None,
    non_assigned_review_diagnostic: bool,
) -> CompletionAuthorityDecision:
    if review_classification is None:
        return CompletionAuthorityDecision(
            issue_number=issue_number,
            tracked_reviewer=tracked_reviewer,
            head_sha=head_sha,
            completion_state="not_completed",
            completion_timestamp=None,
            timestamp_source="none",
            source_review_id=None,
            source_review_state=None,
            non_assigned_review_diagnostic=non_assigned_review_diagnostic,
            can_set_review_completed_at=False,
            diagnostic_reason="no_review_classification",
        )
    if review_classification.classified_scope != "current_head_assigned_reviewer":
        return CompletionAuthorityDecision(
            issue_number=issue_number,
            tracked_reviewer=tracked_reviewer,
            head_sha=head_sha,
            completion_state="not_completed",
            completion_timestamp=None,
            timestamp_source="non_assigned_review_diagnostic" if non_assigned_review_diagnostic else "none",
            source_review_id=review_classification.review_id,
            source_review_state=review_classification.state,
            non_assigned_review_diagnostic=non_assigned_review_diagnostic,
            can_set_review_completed_at=False,
            diagnostic_reason=review_classification.diagnostic_reason,
        )
    if not review_classification.submitted_at:
        return CompletionAuthorityDecision(
            issue_number=issue_number,
            tracked_reviewer=tracked_reviewer,
            head_sha=head_sha,
            completion_state="blocked",
            completion_timestamp=None,
            timestamp_source="blocked_missing_timestamp",
            source_review_id=review_classification.review_id,
            source_review_state=review_classification.state,
            non_assigned_review_diagnostic=False,
            can_set_review_completed_at=False,
            diagnostic_reason="missing_review_submitted_at",
        )
    return CompletionAuthorityDecision(
        issue_number=issue_number,
        tracked_reviewer=tracked_reviewer,
        head_sha=head_sha,
        completion_state="completed_by_tracked_reviewer",
        completion_timestamp=review_classification.submitted_at,
        timestamp_source="current_head_tracked_reviewer_review",
        source_review_id=review_classification.review_id,
        source_review_state=review_classification.state,
        non_assigned_review_diagnostic=False,
        can_set_review_completed_at=True,
        diagnostic_reason=None,
    )


def derive_write_approval_authority_decision(
    *,
    issue_number: int | None,
    head_sha: str | None,
    assigned_reviewer: str | None,
    assigned_review_classification: live_review_support.ReviewFreshnessClassification | None,
    visible_review_classifications: tuple[live_review_support.ReviewFreshnessClassification, ...],
    permission_evidence: object | None,
    dismissal_evidence: object | None,
) -> WriteApprovalAuthorityDecision:
    del dismissal_evidence
    assigned_complete = assigned_review_classification is not None and assigned_review_classification.classified_scope == "current_head_assigned_reviewer"
    assigned_state = assigned_review_classification.state if assigned_review_classification is not None else None
    if not assigned_complete:
        return WriteApprovalAuthorityDecision(
            issue_number=issue_number,
            head_sha=head_sha,
            assigned_reviewer=assigned_reviewer,
            assigned_review_id=assigned_review_classification.review_id if assigned_review_classification else None,
            assigned_review_state=assigned_state,
            assigned_round_complete=False,
            write_approval_state="blocked_unavailable_authority",
            write_approval_source="blocked_untrusted_review_reads",
            approving_reviewer=None,
            approving_review_id=None,
            permission_source=None,
            dismissal_supersession_status="blocked_untrusted",
            response_state="projection_failed",
            diagnostic_reason="assigned_round_not_complete",
            can_project_final_state=False,
        )
    if assigned_state != "APPROVED":
        return WriteApprovalAuthorityDecision(
            issue_number=issue_number,
            head_sha=head_sha,
            assigned_reviewer=assigned_reviewer,
            assigned_review_id=assigned_review_classification.review_id,
            assigned_review_state=assigned_state,
            assigned_round_complete=True,
            write_approval_state="not_required_for_non_approval_round_completion",
            write_approval_source="assigned_reviewer_current_head_non_approval_review",
            approving_reviewer=assigned_review_classification.author,
            approving_review_id=assigned_review_classification.review_id,
            permission_source="not_required_for_non_approval_round_completion",
            dismissal_supersession_status="pass_not_dismissed_or_superseded",
            response_state="awaiting_contributor_response",
            diagnostic_reason=None,
            can_project_final_state=True,
        )
    permission_map = (
        {str(login).lower(): status for login, status in permission_evidence.items() if isinstance(login, str)}
        if isinstance(permission_evidence, dict)
        else {}
    )
    for classification in visible_review_classifications:
        if classification.state != "APPROVED" or classification.classified_scope not in {
            "current_head_assigned_reviewer",
            "current_head_alternate_reviewer",
        }:
            continue
        permission = permission_map.get((classification.author or "").lower(), "unavailable")
        if permission == "unavailable" and permission_map:
            return WriteApprovalAuthorityDecision(
                issue_number=issue_number,
                head_sha=head_sha,
                assigned_reviewer=assigned_reviewer,
                assigned_review_id=assigned_review_classification.review_id,
                assigned_review_state=assigned_state,
                assigned_round_complete=True,
                write_approval_state="blocked_unavailable_authority",
                write_approval_source="github_permission_read_unavailable",
                approving_reviewer=classification.author,
                approving_review_id=classification.review_id,
                permission_source="github_permission_read",
                dismissal_supersession_status="blocked_untrusted",
                response_state="projection_failed",
                diagnostic_reason="permission_unavailable",
                can_project_final_state=False,
            )
        assigned_reviewer_approval_without_permission_read = (
            classification.author == assigned_review_classification.author and not permission_map
        )
        if permission == "granted" or assigned_reviewer_approval_without_permission_read:
            return WriteApprovalAuthorityDecision(
                issue_number=issue_number,
                head_sha=head_sha,
                assigned_reviewer=assigned_reviewer,
                assigned_review_id=assigned_review_classification.review_id,
                assigned_review_state=assigned_state,
                assigned_round_complete=True,
                write_approval_state="visible_write_approval",
                write_approval_source=(
                    "assigned_reviewer_current_head_approval"
                    if classification.author == assigned_review_classification.author
                    else "non_assigned_current_head_write_approval_after_assigned_round"
                ),
                approving_reviewer=classification.author,
                approving_review_id=classification.review_id,
                permission_source="github_permission_read" if permission_map else None,
                dismissal_supersession_status="pass_not_dismissed_or_superseded",
                response_state="done",
                diagnostic_reason=None,
                can_project_final_state=True,
            )
    return WriteApprovalAuthorityDecision(
        issue_number=issue_number,
        head_sha=head_sha,
        assigned_reviewer=assigned_reviewer,
        assigned_review_id=assigned_review_classification.review_id,
        assigned_review_state=assigned_state,
        assigned_round_complete=True,
        write_approval_state="visibly_missing_write_approval",
        write_approval_source="none_visible_after_trusted_reads",
        approving_reviewer=None,
        approving_review_id=None,
        permission_source="github_permission_read" if permission_map else None,
        dismissal_supersession_status="pass_not_dismissed_or_superseded",
        response_state="awaiting_write_approval",
        diagnostic_reason=None,
        can_project_final_state=True,
    )


def compute_pr_approval_state_from_reviews(
    survivors: dict[str, dict],
    *,
    current_reviewer: str | None,
    current_head: str,
    permission_statuses: dict[str, str],
) -> dict[str, object]:
    approvals = [review for review in survivors.values() if str(review.get("state", "")).upper() == "APPROVED"]
    current_reviewer_approvals = []
    current_reviewer_key = current_reviewer.lower() if isinstance(current_reviewer, str) and current_reviewer.strip() else None
    if current_reviewer_key is not None:
        for review in approvals:
            author = review.get("user", {}).get("login")
            if isinstance(author, str) and author.lower() == current_reviewer_key:
                current_reviewer_approvals.append(review)
    completion = {
        "completed": bool(current_reviewer_approvals),
        "current_head_sha": current_head,
        "qualifying_review_ids": [review.get("id") for review in current_reviewer_approvals],
    }

    has_write_approval = False
    write_approvers: list[str] = []
    for review in approvals:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author.strip():
            continue
        status = permission_statuses.get(author.lower(), "unavailable")
        if status == "unavailable":
            return {"ok": False, "reason": "permission_unavailable"}
        if status == "granted":
            has_write_approval = True
            write_approvers.append(author)

    write_approval = {
        "has_write_approval": has_write_approval,
        "write_approvers": write_approvers,
        "current_head_sha": current_head,
    }
    return {
        "ok": True,
        "completion": completion,
        "write_approval": write_approval,
        "current_head_sha": current_head,
    }


def compute_pr_approval_state_result(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews: list[dict] | None = None,
) -> dict[str, object]:
    boundary = live_review_support.get_current_cycle_boundary(
        review_data,
        parse_timestamp=bot.parse_iso8601_timestamp,
    )
    if boundary is None:
        return live_review_support.projection_failure_result("pull_request_unavailable")
    pull_request_result = live_review_support.read_pull_request_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return pull_request_result
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return live_review_support.projection_failure_result("pull_request_head_unavailable", "invalid_payload")
    reviews_result = live_review_support.read_pull_request_reviews_result(bot, issue_number, reviews)
    if not reviews_result.get("ok"):
        return reviews_result
    reviews = reviews_result["reviews"]
    context = live_review_support.build_current_review_context(
        bot,
        issue_number,
        review_data,
        pull_request=pull_request,
        reviews=reviews,
    )
    if not context.live_reviews_available:
        return live_review_support.projection_failure_result(str(context.live_reviews_failure_kind or "reviews_unavailable"))
    current_reviewer = review_data.get("current_reviewer") if isinstance(review_data.get("current_reviewer"), str) else None
    current_head_classifications = tuple(
        classification
        for classification in context.classifications
        if classification.classified_scope in {"current_head_assigned_reviewer", "current_head_alternate_reviewer"}
    )
    assigned_classifications = tuple(
        classification
        for classification in current_head_classifications
        if classification.classified_scope == "current_head_assigned_reviewer"
    )
    assigned_classification = max(
        assigned_classifications,
        key=lambda item: (item.submitted_at or "", str(item.review_id)),
        default=None,
    )
    completion_decision = derive_completion_authority_decision(
        issue_number=issue_number,
        tracked_reviewer=current_reviewer,
        head_sha=current_head,
        review_classification=assigned_classification,
        non_assigned_review_diagnostic=any(
            item.classified_scope == "current_head_alternate_reviewer" for item in current_head_classifications
        ),
    )
    if not completion_decision.can_set_review_completed_at:
        return {
            "ok": True,
            "completion": {
                "completed": False,
                "current_head_sha": current_head,
                "qualifying_review_ids": [],
                "authority_decision": completion_decision.to_output(),
            },
            "write_approval": {
                "has_write_approval": False,
                "write_approvers": [],
                "current_head_sha": current_head,
                "response_state": "awaiting_reviewer_response",
            },
            "current_head_sha": current_head,
        }
    permission_evidence = {}
    for classification in current_head_classifications:
        if classification.state != "APPROVED" or not classification.author:
            continue
        permission_evidence[classification.author.lower()] = live_review_support.permission_status(bot, classification.author, "push")
    write_decision = derive_write_approval_authority_decision(
        issue_number=issue_number,
        head_sha=current_head,
        assigned_reviewer=current_reviewer,
        assigned_review_classification=assigned_classification,
        visible_review_classifications=current_head_classifications,
        permission_evidence=permission_evidence,
        dismissal_evidence=None,
    )
    if write_decision.response_state == "projection_failed":
        return live_review_support.projection_failure_result(write_decision.diagnostic_reason or write_decision.write_approval_state)
    completion = {
        "completed": completion_decision.can_set_review_completed_at,
        "current_head_sha": current_head,
        "qualifying_review_ids": (
            [completion_decision.source_review_id] if completion_decision.can_set_review_completed_at else []
        ),
        "authority_decision": completion_decision.to_output(),
    }
    write_approval = {
        "has_write_approval": write_decision.response_state == "done",
        "write_approvers": [write_decision.approving_reviewer] if write_decision.response_state == "done" and write_decision.approving_reviewer else [],
        "current_head_sha": current_head,
        "response_state": write_decision.response_state,
        "authority_decision": write_decision.to_output(),
    }
    return {
        "ok": True,
        "completion": completion,
        "write_approval": write_approval,
        "current_head_sha": current_head,
    }


def find_triage_approval_after(bot, reviews: list[dict], since) -> tuple[str, object] | None:
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[object, str, str]] = []
    for review in reviews:
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue
        submitted_at = live_review_support.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, str(review.get("id", "")), author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = live_review_support.permission_status(bot, author, "triage") == "granted"
        if permission_cache[cache_key]:
            return author, submitted_at
    return None
