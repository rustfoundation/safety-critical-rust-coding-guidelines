def issue_comment_event(comment_id: int, *, created_at: str, login: str = "alice", user_type: str = "User") -> dict:
    return {
        "id": comment_id,
        "created_at": created_at,
        "user": {"login": login, "type": user_type},
    }


def review_comment_event(comment_id: int, *, created_at: str, login: str = "dana", user_type: str = "User") -> dict:
    return {
        "id": comment_id,
        "created_at": created_at,
        "user": {"login": login, "type": user_type},
    }


def pull_request_review_event(
    review_id: int,
    *,
    submitted_at: str,
    state: str,
    commit_id: str | None = None,
    login: str = "alice",
    updated_at: str | None = None,
) -> dict:
    payload = {
        "id": review_id,
        "submitted_at": submitted_at,
        "state": state,
        "user": {"login": login},
    }
    if commit_id is not None:
        payload["commit_id"] = commit_id
    if updated_at is not None:
        payload["updated_at"] = updated_at
    return payload


def workflow_run(
    run_id: int,
    *,
    event: str,
    path: str,
    created_at: str,
    repo_full_name: str = "rustfoundation/safety-critical-rust-coding-guidelines",
    pr_number: int | None = 42,
    status: str | None = None,
    conclusion: str | None = None,
    name: str | None = None,
) -> dict:
    payload = {
        "id": run_id,
        "event": event,
        "path": path,
        "created_at": created_at,
        "repository": {"full_name": repo_full_name},
        "pull_requests": [] if pr_number is None else [{"number": pr_number}],
    }
    if status is not None:
        payload["status"] = status
    if conclusion is not None:
        payload["conclusion"] = conclusion
    if name is not None:
        payload["name"] = name
    return payload


def artifact_payload(
    *,
    source_event_key: str,
    source_run_id: int,
    pr_number: int = 42,
    source_run_attempt: int = 1,
) -> dict:
    return {
        "source_event_key": source_event_key,
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "pr_number": pr_number,
    }
