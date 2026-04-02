from scripts import reviewer_bot


def make_tracked_review_state(
    state: dict,
    issue_number: int,
    *,
    reviewer: str | None = None,
    assigned_at: str | None = None,
    active_cycle_started_at: str | None = None,
    repair_needed: dict | None = None,
):
    review = reviewer_bot.ensure_review_entry(state, issue_number, create=True)
    if review is None:
        raise AssertionError(f"Unable to create review entry for #{issue_number}")
    if reviewer is not None:
        review["current_reviewer"] = reviewer
    if assigned_at is not None:
        review["assigned_at"] = assigned_at
    if active_cycle_started_at is not None:
        review["active_cycle_started_at"] = active_cycle_started_at
    if repair_needed is not None:
        review["repair_needed"] = repair_needed
    return review


def issue_snapshot(
    issue_number: int,
    *,
    state: str = "open",
    is_pull_request: bool = False,
    labels: list[dict] | list[str] | None = None,
) -> dict:
    return {
        "number": issue_number,
        "state": state,
        "pull_request": {} if is_pull_request else None,
        "labels": labels or [],
    }


def pull_request_payload(
    issue_number: int,
    *,
    head_sha: str,
    author: str = "alice",
    head_repo_full_name: str | None = None,
) -> dict:
    payload = {
        "number": issue_number,
        "state": "open",
        "head": {"sha": head_sha},
        "user": {"login": author},
    }
    if head_repo_full_name is not None:
        payload["head"]["repo"] = {"full_name": head_repo_full_name}
    return payload


def review_payload(
    review_id: int,
    *,
    state: str,
    submitted_at: str,
    commit_id: str,
    author: str,
) -> dict:
    return {
        "id": review_id,
        "state": state,
        "submitted_at": submitted_at,
        "commit_id": commit_id,
        "user": {"login": author},
    }


def accept_reviewer_comment(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
) -> bool:
    return reviewer_bot.reviews_module.accept_channel_event(
        review_data,
        "reviewer_comment",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
    )


def accept_reviewer_review(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
    reviewed_head_sha: str,
    source_precedence: int = 1,
) -> bool:
    return reviewer_bot.reviews_module.accept_channel_event(
        review_data,
        "reviewer_review",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
        reviewed_head_sha=reviewed_head_sha,
        source_precedence=source_precedence,
    )


def accept_contributor_comment(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
) -> bool:
    return reviewer_bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_comment",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
    )


def accept_contributor_revision(
    review_data: dict,
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
    head_sha: str,
) -> bool:
    return reviewer_bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=semantic_key,
        timestamp=timestamp,
        actor=actor,
        reviewed_head_sha=head_sha,
    )


def accepted_record(
    *,
    semantic_key: str,
    timestamp: str,
    actor: str,
    reviewed_head_sha: str | None = None,
    head_sha: str | None = None,
) -> dict:
    record = {
        "semantic_key": semantic_key,
        "timestamp": timestamp,
        "actor": actor,
    }
    if reviewed_head_sha is not None:
        record["reviewed_head_sha"] = reviewed_head_sha
    if head_sha is not None:
        record["head_sha"] = head_sha
    return record
