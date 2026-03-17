"""Reviewer-bot event, deferred-evidence, and freshness handlers."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import yaml

from .guidance import get_fls_audit_guidance, get_issue_guidance, get_pr_guidance


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def _is_pr_event() -> bool:
    return os.environ.get("IS_PULL_REQUEST", "false").lower() == "true"


def _require_v18_for_pr(state: dict, context: str) -> bool:
    if not _is_pr_event():
        return True
    epoch = _runtime_epoch(state)
    if epoch != "freshness_v15":
        print(f"V18 PR freshness path safe-noop for {context}; epoch is {epoch}")
        return False
    return True


def _require_legacy_for_legacy_pr(state: dict, context: str) -> bool:
    if not _is_pr_event():
        return True
    epoch = _runtime_epoch(state)
    if epoch == "freshness_v15":
        print(f"Legacy PR freshness path safe-noop for {context}; epoch is {epoch}")
        return False
    return True


def _normalize_comment_body(body: str) -> str:
    return "\n".join(line.rstrip() for line in body.replace("\r\n", "\n").split("\n")).strip()


def _semantic_digest(value: str) -> str:
    return hashlib.sha256(_normalize_comment_body(value).encode("utf-8")).hexdigest()


def _digest_body(body: str) -> str:
    return hashlib.sha256(_normalize_comment_body(body).encode("utf-8")).hexdigest()


def _comment_line_is_command(bot, line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    pattern = rf"^{re.escape(bot.BOT_MENTION)}\s+/[A-Za-z0-9?_-]+(?:\s+.*)?$"
    return re.match(pattern, stripped) is not None


def classify_comment_payload(bot, body: str) -> dict:
    normalized = _normalize_comment_body(bot.strip_code_blocks(body))
    if not normalized:
        return {
            "comment_class": "empty_or_whitespace",
            "has_non_command_text": False,
            "command_count": 0,
            "command": None,
            "args": [],
            "normalized_body": normalized,
        }
    lines = [line for line in normalized.splitlines() if line.strip()]
    command_lines = [line for line in lines if _comment_line_is_command(bot, line)]
    non_command_lines = [line for line in lines if not _comment_line_is_command(bot, line)]
    parsed = bot.parse_command(normalized)
    command = None
    args: list[str] = []
    if parsed:
        command, args = parsed
    if command_lines and not non_command_lines:
        comment_class = "command_only"
    elif command_lines and non_command_lines:
        comment_class = "command_plus_text"
    else:
        comment_class = "plain_text"
    return {
        "comment_class": comment_class,
        "has_non_command_text": bool(non_command_lines),
        "command_count": len(command_lines),
        "command": command,
        "args": args,
        "normalized_body": normalized,
    }


def classify_issue_comment_actor() -> str:
    comment_user_type = os.environ.get("COMMENT_USER_TYPE", "").strip()
    comment_author = os.environ.get("COMMENT_AUTHOR", "").strip()
    sender_type = os.environ.get("COMMENT_SENDER_TYPE", "").strip()
    installation_id = os.environ.get("COMMENT_INSTALLATION_ID", "").strip()
    via_github_app = os.environ.get("COMMENT_PERFORMED_VIA_GITHUB_APP", "").strip().lower()
    if comment_user_type == "Bot" or comment_author.endswith("[bot]"):
        return "bot_account"
    if installation_id or via_github_app == "true" or (sender_type and sender_type not in {"User", "Bot"}):
        return "github_app_or_other_automation"
    if comment_user_type == "User" and comment_author and not comment_author.endswith("[bot]") and not installation_id and via_github_app != "true":
        return "repo_user_principal"
    return "unknown_actor"


def get_latest_review_by_reviewer(bot, reviews: list[dict], reviewer: str) -> dict | None:
    latest_review = None
    latest_key = (datetime.min.replace(tzinfo=timezone.utc), "")
    for review in reviews:
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or author.lower() != reviewer.lower():
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        review_id = str(review.get("id", ""))
        review_key = (submitted_at, review_id)
        if review_key >= latest_key:
            latest_key = review_key
            latest_review = review
    return latest_review


def find_triage_approval_after(bot, reviews: list[dict], since: datetime | None) -> tuple[str, datetime] | None:
    permission_cache: dict[str, bool] = {}
    approvals: list[tuple[datetime, str, str]] = []
    for review in reviews:
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, str(review.get("id", "")), author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = bot.is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at
    return None


def _ensure_source_event_key(review_data: dict, source_event_key: str, payload: dict | None = None) -> None:
    review_data.setdefault("deferred_gaps", {})
    if payload is None:
        payload = {}
    payload["source_event_key"] = source_event_key
    review_data["deferred_gaps"][source_event_key] = payload


def _clear_source_event_key(review_data: dict, source_event_key: str) -> None:
    deferred_gaps = review_data.get("deferred_gaps")
    if isinstance(deferred_gaps, dict):
        deferred_gaps.pop(source_event_key, None)


def _mark_reconciled_source_event(review_data: dict, source_event_key: str) -> None:
    reconciled = review_data.setdefault("reconciled_source_events", [])
    if source_event_key not in reconciled:
        reconciled.append(source_event_key)


def _was_reconciled_source_event(review_data: dict, source_event_key: str) -> bool:
    reconciled = review_data.get("reconciled_source_events")
    return isinstance(reconciled, list) and source_event_key in reconciled


def _record_review_rebuild(bot, state: dict, issue_number: int, review_data: dict) -> bool:
    pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch pull request #{issue_number}")
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        raise RuntimeError(f"Failed to fetch live reviews for PR #{issue_number}")
    completion, _ = bot.reviews_module.rebuild_pr_approval_state(bot, issue_number, review_data, pull_request=pull_request, reviews=reviews)
    if completion is None:
        raise RuntimeError(f"Unable to rebuild approval state for PR #{issue_number}")
    latest = bot.get_latest_review_by_reviewer(reviews, str(review_data.get("current_reviewer", "")))
    if latest is not None:
        commit_id = latest.get("commit_id")
        submitted_at = latest.get("submitted_at")
        if isinstance(commit_id, str) and isinstance(submitted_at, str):
            bot.reviews_module.accept_channel_event(
                review_data,
                "reviewer_review",
                semantic_key=f"pull_request_review:{latest.get('id')}",
                timestamp=submitted_at,
                actor=review_data.get("current_reviewer"),
                reviewed_head_sha=commit_id,
                source_precedence=1,
            )
    return bool(completion.get("completed"))


def reconcile_active_review_entry(
    bot,
    state: dict,
    issue_number: int,
    *,
    require_pull_request_context: bool = True,
    completion_source: str = "rectify:reconcile-pr-review",
) -> tuple[str, bool, bool]:
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return f"ℹ️ No active review entry exists for #{issue_number}; nothing to rectify.", True, False
    assigned_reviewer = review_data.get("current_reviewer")
    if not assigned_reviewer:
        return f"ℹ️ #{issue_number} has no tracked assigned reviewer; nothing to rectify.", True, False
    if require_pull_request_context and not _is_pr_event():
        return f"ℹ️ #{issue_number} is not a pull request in this event context; `/rectify` only reconciles PR reviews.", True, False
    if not _require_v18_for_pr(state, "rectify"):
        return "ℹ️ PR review freshness rectify is epoch-gated and currently inactive.", True, False
    state_changed = maybe_record_head_observation_repair(bot, issue_number, review_data)
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return f"❌ Failed to fetch reviews for PR #{issue_number}; cannot run `/rectify`.", False, False
    latest_review = bot.get_latest_review_by_reviewer(reviews, assigned_reviewer)
    messages: list[str] = []
    if latest_review is not None:
        latest_state = str(latest_review.get("state", "")).upper()
        commit_id = latest_review.get("commit_id")
        submitted_at = latest_review.get("submitted_at")
        if latest_state in {"APPROVED", "COMMENTED", "CHANGES_REQUESTED"} and isinstance(commit_id, str) and isinstance(submitted_at, str):
            state_changed = bot.reviews_module.accept_channel_event(
                review_data,
                "reviewer_review",
                semantic_key=f"pull_request_review:{latest_review.get('id')}",
                timestamp=submitted_at,
                actor=assigned_reviewer,
                reviewed_head_sha=commit_id,
                source_precedence=1,
            ) or state_changed
            messages.append(f"latest review by @{assigned_reviewer} is `{latest_state}`")
    if _record_review_rebuild(bot, state, issue_number, review_data):
        state_changed = True
        review_data["review_completion_source"] = completion_source
    if review_data.get("mandatory_approver_required"):
        escalation_opened_at = bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_pinged_at")) or bot.parse_iso8601_timestamp(review_data.get("mandatory_approver_label_applied_at"))
        triage_approval = find_triage_approval_after(bot, reviews, escalation_opened_at)
        if triage_approval is not None:
            approver, _ = triage_approval
            if bot.satisfy_mandatory_approver_requirement(state, issue_number, approver):
                state_changed = True
                messages.append(f"mandatory triage approval satisfied by @{approver}")
    if state_changed:
        return f"✅ Rectified PR #{issue_number}: {'; '.join(messages) or 'reconciled live review state'}.", True, True
    return f"ℹ️ Rectify checked PR #{issue_number}: {'; '.join(messages) or 'no reconciliation transitions applied'}.", True, False


def handle_transition_notice(bot, state: dict, issue_number: int, reviewer: str) -> bool:
    notice_message = f"""🔔 **Transition Period Ended**

@{reviewer}, the {bot.TRANSITION_PERIOD_DAYS}-day transition period has passed without activity on this review.

Per our [contribution guidelines](CONTRIBUTING.md#review-deadlines), this may result in a transition from Producer to Observer status.

**The review will now be reassigned to the next person in the queue.**

_If you believe this is in error or have extenuating circumstances, please reach out to the subcommittee._"""
    bot.post_comment(issue_number, notice_message)
    return True


def handle_issue_or_pr_opened(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_or_pr_opened")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_key = str(issue_number)
    tracked_reviewer = None
    if isinstance(state.get("active_reviews"), dict) and issue_key in state["active_reviews"]:
        review_data = state["active_reviews"][issue_key]
        if isinstance(review_data, dict):
            tracked_reviewer = review_data.get("current_reviewer")
    if tracked_reviewer:
        return False
    current_assignees = bot.get_issue_assignees(issue_number)
    if current_assignees:
        return False
    labels_json = os.environ.get("ISSUE_LABELS", "[]")
    try:
        labels = json.loads(labels_json)
    except json.JSONDecodeError:
        labels = []
    if not any(label in bot.REVIEW_LABELS for label in labels):
        return False
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    reviewer = bot.get_next_reviewer(state, skip_usernames={issue_author} if issue_author else set())
    if not reviewer:
        bot.post_comment(issue_number, f"⚠️ No reviewers available in the queue. Please use `{bot.BOT_MENTION} /sync-members` to update the queue.")
        return False
    is_pr = _is_pr_event()
    assignment_attempt = bot.request_reviewer_assignment(issue_number, reviewer)
    bot.set_current_reviewer(state, issue_number, reviewer)
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if is_pr and isinstance(review_data, dict):
        head_sha = os.environ.get("PR_HEAD_SHA", "").strip()
        if head_sha:
            review_data["active_head_sha"] = head_sha
    bot.record_assignment(state, reviewer, issue_number, "pr" if is_pr else "issue")
    failure_comment = bot.get_assignment_failure_comment(reviewer, assignment_attempt)
    if failure_comment:
        bot.post_comment(issue_number, failure_comment)
    if is_pr and assignment_attempt.success:
        bot.post_comment(issue_number, get_pr_guidance(reviewer, issue_author))
    if not is_pr:
        guidance = get_fls_audit_guidance(reviewer, issue_author) if bot.FLS_AUDIT_LABEL in labels else get_issue_guidance(reviewer, issue_author)
        bot.post_comment(issue_number, guidance)
    return True


def handle_issue_edited_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_issue_edited_event")
    if _is_pr_event():
        return False
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_author = os.environ.get("ISSUE_AUTHOR", "").strip()
    editor = os.environ.get("SENDER_LOGIN", "").strip() or issue_author
    if not issue_author or editor.lower() != issue_author.lower():
        return False
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None:
        return False
    updated_at = os.environ.get("ISSUE_UPDATED_AT", "").strip() or _now_iso()
    current_title = os.environ.get("ISSUE_TITLE", "")
    current_body = os.environ.get("ISSUE_BODY", "")
    previous_title = os.environ.get("ISSUE_CHANGES_TITLE_FROM", "")
    previous_body = os.environ.get("ISSUE_CHANGES_BODY_FROM", "")
    title_changed = _normalize_comment_body(current_title) != _normalize_comment_body(previous_title)
    body_changed = _normalize_comment_body(current_body) != _normalize_comment_body(previous_body)
    if not title_changed and not body_changed:
        return False
    if title_changed and body_changed:
        semantic_key = f"issues_edit_title_body:{issue_number}:{_semantic_digest(current_title)}:{_semantic_digest(current_body)}"
    elif title_changed:
        semantic_key = f"issues_edit_title:{issue_number}:{_semantic_digest(current_title)}"
    else:
        semantic_key = f"issues_edit_body:{issue_number}:{_semantic_digest(current_body)}"
    return bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_comment",
        semantic_key=semantic_key,
        timestamp=updated_at,
        actor=issue_author,
        source_precedence=0,
    )


def handle_labeled_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_labeled_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    label_name = os.environ.get("LABEL_NAME", "")
    is_pr = _is_pr_event()
    bot.collect_touched_item(issue_number)
    if label_name == "sign-off: create pr":
        if is_pr:
            return False
        review_data = bot.ensure_review_entry(state, issue_number)
        reviewer = review_data.get("current_reviewer") if review_data else None
        return bot.mark_review_complete(state, issue_number, reviewer, "issue_label: sign-off: create pr")
    if label_name not in bot.REVIEW_LABELS:
        return False
    return handle_issue_or_pr_opened(bot, state)


def handle_pull_request_target_synchronize(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_pull_request_target_synchronize")
    if _runtime_epoch(state) != "freshness_v15":
        print("V18 synchronize repair safe-noop before epoch flip")
        return False
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    review_data = bot.ensure_review_entry(state, issue_number)
    if review_data is None or not review_data.get("current_reviewer"):
        return False
    head_sha = os.environ.get("PR_HEAD_SHA", "").strip()
    if not head_sha:
        raise RuntimeError("Missing PR_HEAD_SHA for synchronize event")
    bot.collect_touched_item(issue_number)
    review_data["active_head_sha"] = head_sha
    timestamp = os.environ.get("EVENT_CREATED_AT", "") or _now_iso()
    changed = bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=f"pull_request_sync:{issue_number}:{head_sha}",
        timestamp=timestamp,
        reviewed_head_sha=head_sha,
        source_precedence=1,
    )
    bot.reviews_module.rebuild_pr_approval_state(bot, issue_number, review_data)
    return changed


def maybe_record_head_observation_repair(bot, issue_number: int, review_data: dict) -> bool:
    pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch live PR #{issue_number} for head observation repair")
    if str(pull_request.get("state", "")).lower() != "open":
        return False
    head = pull_request.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(head_sha, str) or not head_sha.strip():
        raise RuntimeError(f"Pull request #{issue_number} is missing a usable head SHA")
    head_sha = head_sha.strip()
    current_head = review_data.get("active_head_sha")
    if current_head == head_sha:
        return False
    contributor_revision = review_data.get("contributor_revision", {}).get("accepted")
    if isinstance(contributor_revision, dict) and contributor_revision.get("reviewed_head_sha") == head_sha:
        review_data["active_head_sha"] = head_sha
        return False
    changed = bot.reviews_module.accept_channel_event(
        review_data,
        "contributor_revision",
        semantic_key=f"pull_request_head_observed:{issue_number}:{head_sha}",
        timestamp=_now_iso(),
        reviewed_head_sha=head_sha,
        source_precedence=0,
    )
    review_data["active_head_sha"] = head_sha
    review_data["current_cycle_completion"] = {}
    review_data["current_cycle_write_approval"] = {}
    review_data["review_completed_at"] = None
    review_data["review_completed_by"] = None
    review_data["review_completion_source"] = None
    return changed


def _is_self_comment(bot, author: str) -> bool:
    return author.strip().lower() == bot.BOT_NAME.lower() or author.strip().lower() == bot.BOT_MENTION.lstrip("@").lower()


def _fetch_pr_metadata(bot, issue_number: int) -> dict:
    pull_request = bot.github_api("GET", f"pulls/{issue_number}")
    if not isinstance(pull_request, dict):
        raise RuntimeError(f"Failed to fetch live PR metadata for #{issue_number}")
    if not isinstance(pull_request.get("head"), dict) or not isinstance(pull_request.get("user"), dict):
        raise RuntimeError(f"Unusable PR metadata for #{issue_number}")
    return pull_request


def route_issue_comment_trust(bot, issue_number: int) -> str:
    actor_class = classify_issue_comment_actor()
    if actor_class in {"bot_account", "github_app_or_other_automation"} or _is_self_comment(bot, os.environ.get("COMMENT_AUTHOR", "")):
        return "safe_noop"
    if not _is_pr_event():
        return "issue_direct"
    pull_request = _fetch_pr_metadata(bot, issue_number)
    head_repo = pull_request.get("head", {}).get("repo", {})
    head_full_name = head_repo.get("full_name") if isinstance(head_repo, dict) else None
    if not isinstance(head_full_name, str) or not head_full_name:
        raise RuntimeError("Missing PR head repository metadata for trust routing")
    is_cross_repo = head_full_name != os.environ.get("GITHUB_REPOSITORY", "")
    pr_author = pull_request.get("user", {}).get("login")
    is_dependabot_restricted = pr_author == "dependabot[bot]"
    author_association = os.environ.get("COMMENT_AUTHOR_ASSOCIATION", "").strip()
    workflow_file = os.environ.get("CURRENT_WORKFLOW_FILE", "").strip()
    workflow_ref = os.environ.get("GITHUB_REF", "").strip()
    direct_match = (
        not is_cross_repo
        and not is_dependabot_restricted
        and actor_class == "repo_user_principal"
        and author_association in bot.AUTHOR_ASSOCIATION_TRUST_ALLOWLIST
        and workflow_file == ".github/workflows/reviewer-bot-pr-comment-trusted.yml"
        and workflow_ref == "refs/heads/main"
    )
    if is_cross_repo or is_dependabot_restricted:
        return "pr_deferred_reconcile"
    if direct_match:
        return "pr_trusted_direct"
    raise RuntimeError("Ambiguous same-repo PR comment trust posture; failing closed")


def _record_conversation_freshness(bot, state: dict, issue_number: int, comment_author: str, comment_id: int, created_at: str) -> bool:
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    issue_author = os.environ.get("ISSUE_AUTHOR", "")
    semantic_key = f"issue_comment:{comment_id}"
    if issue_author and issue_author.lower() == comment_author.lower():
        return bot.reviews_module.accept_channel_event(
            review_data,
            "contributor_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
    current_reviewer = review_data.get("current_reviewer")
    if isinstance(current_reviewer, str) and current_reviewer.lower() == comment_author.lower():
        changed = bot.reviews_module.accept_channel_event(
            review_data,
            "reviewer_comment",
            semantic_key=semantic_key,
            timestamp=created_at,
            actor=comment_author,
        )
        review_data["last_reviewer_activity"] = created_at
        review_data["transition_warning_sent"] = None
        return changed
    return False


def _store_pending_privileged_command(review_data: dict, issue_number: int, source_event_key: str, command_name: str, actor: str, args: list[str]) -> bool:
    pending = review_data.setdefault("pending_privileged_commands", {})
    pending[source_event_key] = {
        "source_event_key": source_event_key,
        "command_name": command_name,
        "issue_number": issue_number,
        "actor": actor,
        "args": args,
        "status": "pending",
        "created_at": _now_iso(),
    }
    return True


def _validate_accept_no_fls_changes_handoff(bot, issue_number: int, comment_author: str) -> tuple[bool, dict]:
    if _is_pr_event():
        return False, {"reason": "pull_request_target_not_allowed"}
    labels = bot.parse_issue_labels()
    if bot.FLS_AUDIT_LABEL not in labels:
        return False, {"reason": "missing_fls_audit_label"}
    if not bot.check_user_permission(comment_author, "triage"):
        return False, {"reason": "authorization_failed"}
    return True, {
        "command_name": "accept-no-fls-changes",
        "issue_number": issue_number,
        "actor": comment_author,
        "authorization": {"required_permission": "triage", "authorized": True},
        "target": {"kind": "issue", "number": issue_number, "labels": sorted(labels)},
    }


def _handle_command(bot, state: dict, issue_number: int, comment_author: str, classified: dict) -> bool:
    command = classified.get("command")
    args = classified.get("args") or []
    if not isinstance(command, str):
        return False
    actor_class = classify_issue_comment_actor()
    if actor_class in {"unknown_actor", "bot_account", "github_app_or_other_automation"}:
        return False
    review_data = bot.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    source_event_key = f"issue_comment:{os.environ.get('COMMENT_ID', '')}"
    if command == "accept-no-fls-changes":
        is_valid, metadata = _validate_accept_no_fls_changes_handoff(bot, issue_number, comment_author)
        if not is_valid:
            bot.post_comment(
                issue_number,
                "❌ This command is not eligible for privileged handoff from the current trusted live state.",
            )
            return False
        stored = _store_pending_privileged_command(review_data, issue_number, source_event_key, command, comment_author, list(args))
        if stored:
            review_data["pending_privileged_commands"][source_event_key].update(metadata)
            bot.post_comment(
                issue_number,
                "✅ Recorded pending privileged command `accept-no-fls-changes` from trusted live validation. Use the isolated privileged workflow to execute it from issue `#314` state.",
            )
        return stored
    if command == "_multiple_commands":
        bot.post_comment(issue_number, f"⚠️ Multiple bot commands in one comment are ignored. Please post a single command per comment. For a list of commands, use `{bot.BOT_MENTION} /commands`.")
        return False
    response = ""
    success = False
    state_changed = False
    if command == "pass":
        response, success = bot.handle_pass_command(state, issue_number, comment_author, " ".join(args) if args else None)
        state_changed = success
    elif command == "away":
        if args:
            response, success = bot.handle_pass_until_command(state, issue_number, comment_author, args[0], " ".join(args[1:]) if len(args) > 1 else None)
            state_changed = success
        else:
            response = f"❌ Missing date. Usage: `{bot.BOT_MENTION} /away YYYY-MM-DD [reason]`"
    elif command == "label":
        response, success = bot.handle_label_command(issue_number, " ".join(args))
    elif command == "sync-members":
        response, success = bot.handle_sync_members_command(state)
        state_changed = success
    elif command == "queue":
        response, success = bot.handle_queue_command(state)
    elif command == "commands":
        response, success = bot.handle_commands_command()
    elif command == "claim":
        response, success = bot.handle_claim_command(state, issue_number, comment_author)
        state_changed = success
    elif command == "release":
        response, success = bot.handle_release_command(state, issue_number, comment_author, list(args))
        state_changed = success
    elif command == "rectify":
        response, success, state_changed = bot.handle_rectify_command(state, issue_number, comment_author)
    elif command == "r?-user":
        response, success = bot.handle_assign_command(state, issue_number, args[0] if args else "")
        state_changed = success
    elif command == "assign-from-queue":
        response, success = bot.handle_assign_from_queue_command(state, issue_number)
        state_changed = success
    elif command == "r?":
        response = f"❌ Missing target. Usage:\n- `{bot.BOT_MENTION} /r? @username` - Assign a specific reviewer\n- `{bot.BOT_MENTION} /r? producers` - Assign next reviewer from queue"
    elif command == "_malformed_known":
        attempted = args[0] if args else "command"
        response = f"⚠️ Did you mean `{bot.BOT_MENTION} /{attempted}`?\n\nCommands require a `/` prefix."
    elif command == "_malformed_unknown":
        attempted = args[0] if args else ""
        response = f"⚠️ Unknown command `{attempted}`. Commands require a `/` prefix.\n\nTry `{bot.BOT_MENTION} /commands` to see available commands."
    else:
        response = f"❌ Unknown command: `/{command}`\n\nAvailable commands:\n{bot.get_commands_help()}"
    comment_id = int(os.environ.get("COMMENT_ID", "0") or 0)
    if comment_id > 0 and command != "_multiple_commands":
        bot.add_reaction(comment_id, "eyes")
        if success:
            bot.add_reaction(comment_id, "+1")
    if response:
        bot.post_comment(issue_number, response)
    return state_changed


def _process_comment_event(bot, state: dict, issue_number: int) -> bool:
    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_author = os.environ.get("COMMENT_AUTHOR", "")
    comment_id = int(os.environ.get("COMMENT_ID", "0") or 0)
    comment_created_at = os.environ.get("COMMENT_CREATED_AT", "") or _now_iso()
    classified = classify_comment_payload(bot, comment_body)
    comment_class = classified["comment_class"]
    state_changed = False
    if comment_class in {"plain_text", "command_plus_text"} and comment_id > 0:
        state_changed = _record_conversation_freshness(bot, state, issue_number, comment_author, comment_id, comment_created_at) or state_changed
    if comment_class in {"command_only", "command_plus_text"} and int(classified.get("command_count", 0)) == 1:
        state_changed = _handle_command(bot, state, issue_number, comment_author, classified) or state_changed
    return state_changed


def handle_comment_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_comment_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    route = route_issue_comment_trust(bot, issue_number)
    if route == "safe_noop":
        return False
    if route == "issue_direct":
        return _process_comment_event(bot, state, issue_number)
    if route == "pr_trusted_direct":
        if not _require_v18_for_pr(state, "pr_trusted_direct_comment"):
            return False
        return _process_comment_event(bot, state, issue_number)
    raise RuntimeError("Deferred PR comment events must not mutate directly in trusted workflows")


def handle_pull_request_review_event(bot, state: dict) -> bool:
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    if _runtime_epoch(state) == "freshness_v15":
        print("Legacy direct pull_request_review mutation disabled after epoch flip")
        return False
    review_action = os.environ.get("EVENT_ACTION", "").strip().lower()
    if review_action not in {"submitted", "dismissed"}:
        return False
    print(f"Deferring pull_request_review {review_action} for #{issue_number}")
    return False


def _validate_deferred_comment_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "comment_id",
        "comment_class",
        "has_non_command_text",
        "source_body_digest",
        "source_created_at",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred comment artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred comment artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("comment_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred comment artifact comment_id and pr_number must be integers")
    if not isinstance(payload.get("comment_class"), str) or not isinstance(payload.get("has_non_command_text"), bool):
        raise RuntimeError("Deferred comment artifact parse fields are malformed")
    if not isinstance(payload.get("source_body_digest"), str) or not isinstance(payload.get("source_created_at"), str):
        raise RuntimeError("Deferred comment artifact source digest or timestamp is malformed")


def _validate_deferred_review_artifact(payload: dict) -> None:
    required = {
        "schema_version",
        "source_workflow_name",
        "source_workflow_file",
        "source_run_id",
        "source_run_attempt",
        "source_event_name",
        "source_event_action",
        "source_event_key",
        "pr_number",
        "review_id",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError("Deferred review artifact missing required fields: " + ", ".join(missing))
    if payload.get("schema_version") != 2:
        raise RuntimeError("Deferred review artifact schema_version is not accepted by V18 reconcile")
    if not isinstance(payload.get("review_id"), int) or not isinstance(payload.get("pr_number"), int):
        raise RuntimeError("Deferred review artifact review_id and pr_number must be integers")


def _load_deferred_context() -> dict:
    path = os.environ.get("DEFERRED_CONTEXT_PATH", "").strip()
    if not path:
        raise RuntimeError("Missing DEFERRED_CONTEXT_PATH for workflow_run reconcile")
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError("Deferred context payload must be a JSON object")
    return payload


def _expected_observer_identity(payload: dict) -> tuple[str, str]:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        return (
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        )
    if event_name == "pull_request_review" and event_action == "submitted":
        return (
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        )
    if event_name == "pull_request_review" and event_action == "dismissed":
        return (
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
        )
    raise RuntimeError("Unsupported deferred workflow identity")


def _validate_workflow_run_artifact_identity(payload: dict) -> None:
    expected_name, expected_file = _expected_observer_identity(payload)
    if payload.get("source_workflow_name") != expected_name:
        raise RuntimeError("Deferred artifact workflow name mismatch")
    if payload.get("source_workflow_file") != expected_file:
        raise RuntimeError("Deferred artifact workflow file mismatch")
    triggering_name = os.environ.get("WORKFLOW_RUN_TRIGGERING_NAME", "").strip()
    if triggering_name and triggering_name != expected_name:
        raise RuntimeError("Triggering workflow name mismatch")
    triggering_id = os.environ.get("WORKFLOW_RUN_TRIGGERING_ID", "").strip()
    if triggering_id and str(payload.get("source_run_id")) != triggering_id:
        raise RuntimeError("Deferred artifact run_id mismatch")
    triggering_attempt = os.environ.get("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "").strip()
    if triggering_attempt and str(payload.get("source_run_attempt")) != triggering_attempt:
        raise RuntimeError("Deferred artifact run_attempt mismatch")
    if os.environ.get("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "").strip() != "success":
        raise RuntimeError("Triggering observer workflow did not conclude successfully")


def _artifact_expected_name(payload: dict) -> str:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    run_id = payload.get("source_run_id")
    run_attempt = payload.get("source_run_attempt")
    if event_name == "issue_comment" and event_action == "created":
        return f"reviewer-bot-comment-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review" and event_action == "submitted":
        return f"reviewer-bot-review-submitted-context-{run_id}-attempt-{run_attempt}"
    if event_name == "pull_request_review" and event_action == "dismissed":
        return f"reviewer-bot-review-dismissed-context-{run_id}-attempt-{run_attempt}"
    raise RuntimeError("Unsupported deferred artifact naming")


def _artifact_expected_payload_name(payload: dict) -> str:
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    if event_name == "issue_comment" and event_action == "created":
        return "deferred-comment.json"
    if event_name == "pull_request_review" and event_action == "submitted":
        return "deferred-review-submitted.json"
    if event_name == "pull_request_review" and event_action == "dismissed":
        return "deferred-review-dismissed.json"
    raise RuntimeError("Unsupported deferred payload path")


def correlate_candidate_observer_runs(
    source_event_key: str,
    *,
    source_event_kind: str,
    source_event_created_at: str,
    pr_number: int,
    workflow_file: str,
    workflow_runs: list[dict] | None,
) -> dict:
    created_at = parse_timestamp(source_event_created_at)
    if created_at is None:
        return {
            "status": "observer_state_unknown",
            "reason": "invalid_source_event_created_at",
            "candidate_run_ids": [],
            "full_scan_complete": False,
            "later_recheck_complete": False,
            "correlated_run": None,
        }
    if workflow_runs is None:
        return {
            "status": "observer_state_unknown",
            "reason": "workflow_run_scan_unavailable",
            "candidate_run_ids": [],
            "full_scan_complete": False,
            "later_recheck_complete": False,
            "correlated_run": None,
        }
    expected_event = "issue_comment" if source_event_kind == "issue_comment:created" else "pull_request_review"
    window_start = created_at - timedelta(minutes=2)
    window_end = created_at + timedelta(minutes=30)
    candidates: list[dict] = []
    for run in workflow_runs:
        if not isinstance(run, dict):
            continue
        if str(run.get("event", "")) != expected_event:
            continue
        created = parse_timestamp(run.get("created_at"))
        if created is None or created < window_start or created > window_end:
            continue
        if str(run.get("path", "")) != workflow_file:
            continue
        repo = run.get("repository")
        if isinstance(repo, dict):
            full_name = repo.get("full_name")
            if isinstance(full_name, str) and full_name != os.environ.get("GITHUB_REPOSITORY", ""):
                continue
        prs = run.get("pull_requests")
        if isinstance(prs, list) and prs:
            if not any(isinstance(pr, dict) and pr.get("number") == pr_number for pr in prs):
                continue
        candidates.append(run)
    candidate_run_ids = [run.get("id") for run in candidates if isinstance(run.get("id"), int)]
    return {
        "status": "candidate_runs_found" if candidates else "no_candidate_runs",
        "reason": None,
        "candidate_runs": candidates,
        "candidate_run_ids": candidate_run_ids,
        "full_scan_complete": True,
        "later_recheck_complete": False,
        "correlated_run": None,
    }


def correlate_run_artifacts_exact(
    payloads_by_run: dict[int, list[dict]] | None,
    source_event_key: str,
    *,
    pr_number: int,
) -> dict:
    if payloads_by_run is None:
        return {"status": "observer_state_unknown", "reason": "artifact_scan_unavailable", "correlated_run": None}
    matches: list[tuple[int, dict]] = []
    candidate_run_ids: list[int] = []
    for run_id, payloads in payloads_by_run.items():
        if not isinstance(run_id, int):
            continue
        candidate_run_ids.append(run_id)
        latest_by_attempt: dict[int, dict] = {}
        for artifact_payload in payloads:
            if not isinstance(artifact_payload, dict):
                continue
            attempt = artifact_payload.get("source_run_attempt")
            if not isinstance(attempt, int):
                continue
            previous = latest_by_attempt.get(attempt)
            if previous is None or artifact_payload.get("source_event_key") == source_event_key:
                latest_by_attempt[attempt] = artifact_payload
        for artifact_payload in latest_by_attempt.values():
            if artifact_payload.get("source_event_key") != source_event_key:
                continue
            if artifact_payload.get("source_run_id") != run_id:
                continue
            if artifact_payload.get("pr_number") != pr_number:
                continue
            matches.append((run_id, artifact_payload))
    if not matches:
        return {
            "status": "no_exact_artifact_match",
            "reason": "no_exact_source_event_key_match",
            "correlated_run": None,
            "candidate_run_ids": sorted(candidate_run_ids),
        }
    distinct_run_ids = sorted({run_id for run_id, _ in matches})
    if len(distinct_run_ids) > 1:
        return {
            "status": "observer_state_unknown",
            "reason": "ambiguous_exact_artifact_matches",
            "correlated_run": None,
            "candidate_run_ids": distinct_run_ids,
        }
    run_id, matched_payload = matches[-1]
    return {
        "status": "exact_artifact_match",
        "reason": None,
        "correlated_run": run_id,
        "artifact_payload": matched_payload,
        "candidate_run_ids": distinct_run_ids,
    }


def _approval_pending_signature_from_runbook() -> dict | None:
    return None


def _fetch_workflow_runs_for_file(bot, workflow_file: str, event_name: str) -> list[dict] | None:
    runs: list[dict] = []
    page = 1
    encoded_workflow = quote(workflow_file, safe="")
    while True:
        response = bot.github_api(
            "GET",
            f"actions/workflows/{encoded_workflow}/runs?event={quote(event_name, safe='')}&per_page=100&page={page}",
        )
        if response is None:
            return None
        workflow_runs = response.get("workflow_runs") if isinstance(response, dict) else None
        if not isinstance(workflow_runs, list):
            return None
        runs.extend([run for run in workflow_runs if isinstance(run, dict)])
        if len(workflow_runs) < 100:
            return runs
        page += 1


def _fetch_run_detail(bot, run_id: int) -> dict | None:
    response = bot.github_api("GET", f"actions/runs/{run_id}")
    if isinstance(response, dict):
        return response
    return None


def _list_run_artifacts(bot, run_id: int) -> list[dict] | None:
    artifacts: list[dict] = []
    page = 1
    while True:
        response = bot.github_api("GET", f"actions/runs/{run_id}/artifacts?per_page=100&page={page}")
        if response is None:
            return None
        page_artifacts = response.get("artifacts") if isinstance(response, dict) else None
        if not isinstance(page_artifacts, list):
            return None
        artifacts.extend([artifact for artifact in page_artifacts if isinstance(artifact, dict)])
        if len(page_artifacts) < 100:
            return artifacts
        page += 1


def _download_artifact_payload(bot, artifact: dict, expected_payload_name: str) -> tuple[str, dict | None]:
    if artifact.get("expired") is True:
        return "expired", None
    download_url = artifact.get("archive_download_url")
    if not isinstance(download_url, str) or not download_url:
        return "missing_download_url", None
    response = bot.requests.request(
        "GET",
        download_url,
        headers={
            "Authorization": f"Bearer {bot.get_github_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if response.status_code >= 400:
        return "download_failed", None
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            payload_files = [name for name in archive.namelist() if not name.endswith("/")]
            if payload_files != [expected_payload_name]:
                return "invalid_payload_layout", None
            with archive.open(expected_payload_name) as handle:
                payload = json.loads(handle.read().decode("utf-8"))
    except (zipfile.BadZipFile, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return "invalid_payload_format", None
    if not isinstance(payload, dict):
        return "invalid_payload_format", None
    return "ok", payload


def inspect_run_artifact_payloads(bot, workflow_runs: list[dict], source_event_key: str, *, pr_number: int, source_event_kind: str) -> dict:
    payloads_by_run: dict[int, list[dict]] = {}
    prior_visibility: dict[int, dict[str, str]] = {}
    artifact_scan_outcomes: dict[int, str] = {}
    event_name, event_action = source_event_kind.split(":", 1)
    expected_payload_name = _artifact_expected_payload_name(
        {
            "source_event_name": event_name,
            "source_event_action": event_action,
        }
    )
    for run in workflow_runs:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        run_attempt = run.get("run_attempt")
        if not isinstance(run_attempt, int):
            continue
        expected_name = _artifact_expected_name(
            {
                "source_event_name": event_name,
                "source_event_action": event_action,
                "source_run_id": run_id,
                "source_run_attempt": run_attempt,
            }
        )
        artifacts = _list_run_artifacts(bot, run_id)
        if artifacts is None:
            return {"status": "observer_state_unknown", "reason": "artifact_listing_unavailable", "payloads_by_run": None}
        filtered = []
        for artifact in artifacts:
            name = artifact.get("name")
            if not isinstance(name, str) or name != expected_name:
                continue
            filtered.append(artifact)
            prior_visibility[run_id] = {"artifact_seen_at": _now_iso()}
            status, payload = _download_artifact_payload(bot, artifact, expected_payload_name)
            if status == "ok" and isinstance(payload, dict):
                payloads_by_run.setdefault(run_id, []).append(payload)
                artifact_scan_outcomes[run_id] = "ok"
            elif status == "expired":
                prior_visibility[run_id]["artifact_last_downloadable_at"] = prior_visibility[run_id]["artifact_seen_at"]
                artifact_scan_outcomes[run_id] = "expired"
            else:
                artifact_scan_outcomes[run_id] = status
        if run_id not in payloads_by_run and filtered:
            payloads_by_run.setdefault(run_id, [])
    result = correlate_run_artifacts_exact(payloads_by_run, source_event_key, pr_number=pr_number)
    result["payloads_by_run"] = payloads_by_run
    result["prior_visibility"] = prior_visibility
    result["artifact_scan_outcomes"] = artifact_scan_outcomes
    return result


def evaluate_deferred_gap_state(
    existing_gap: dict,
    run_correlation: dict,
    run_detail: dict | None,
    artifact_correlation: dict | None,
) -> tuple[str, str]:
    if run_correlation.get("status") == "observer_state_unknown":
        return "observer_state_unknown", str(run_correlation.get("reason") or "run_scan_unknown")
    if run_correlation.get("status") == "no_candidate_runs":
        gap = dict(existing_gap)
        gap["full_scan_complete"] = bool(run_correlation.get("full_scan_complete"))
        gap["later_recheck_complete"] = bool(run_correlation.get("later_recheck_complete"))
        gap["correlated_run_found"] = False
        gap["approval_pending_evidence_retained"] = False
        if can_mark_observer_run_missing(gap):
            return "observer_run_missing", "negative_inference_satisfied"
        created_at = parse_timestamp(existing_gap.get("source_event_created_at"))
        if created_at is not None and _now() < created_at + timedelta(hours=24):
            return "awaiting_observer_run", "missing_run_window_open"
        return "observer_state_unknown", "missing_run_window_not_proven"
    if run_detail is None:
        return "observer_state_unknown", "run_detail_unavailable"
    run_state = observer_run_reason_from_details(run_detail, _approval_pending_signature_from_runbook())
    if run_state in {
        "awaiting_observer_approval",
        "observer_in_progress",
        "observer_failed",
        "observer_cancelled",
        "observer_state_unknown",
    }:
        return run_state, f"run_detail:{run_state}"
    if run_state != "completed_success":
        return "observer_state_unknown", "unmapped_run_state"
    if artifact_correlation is None:
        return "artifact_missing", "artifact_correlation_unavailable"
    artifact_status = artifact_correlation.get("status")
    if artifact_status == "exact_artifact_match":
        return "observer_state_unknown", "successful_artifact_present_without_reconcile_marker"
    if artifact_status == "no_exact_artifact_match":
        scan_outcomes = artifact_correlation.get("artifact_scan_outcomes")
        if isinstance(scan_outcomes, dict):
            if any(outcome == "expired" for outcome in scan_outcomes.values()):
                return "artifact_expired", "prior_visibility_or_retention_proof_required"
            invalid_outcomes = {"missing_download_url", "download_failed", "invalid_payload_layout", "invalid_payload_format"}
            if any(outcome in invalid_outcomes for outcome in scan_outcomes.values()):
                return "artifact_invalid", "artifact_download_or_payload_invalid"
        return "artifact_missing", str(artifact_correlation.get("reason") or "exact_artifact_missing")
    if artifact_status == "observer_state_unknown":
        return "observer_state_unknown", str(artifact_correlation.get("reason") or "artifact_ambiguity")
    return "artifact_invalid", str(artifact_correlation.get("reason") or "artifact_invalid")


def _update_deferred_gap(review_data: dict, payload: dict, reason: str, diagnostic_summary: str) -> None:
    source_event_key = str(payload.get("source_event_key", ""))
    if not source_event_key:
        return
    review_data.setdefault("deferred_gaps", {})
    existing = review_data["deferred_gaps"].get(source_event_key, {})
    if not isinstance(existing, dict):
        existing = {}
    existing.update(
        {
            "source_event_key": source_event_key,
            "source_event_kind": f"{payload.get('source_event_name')}:{payload.get('source_event_action')}",
            "pr_number": payload.get("pr_number"),
            "reason": reason,
            "source_event_created_at": payload.get("source_created_at") or payload.get("source_submitted_at"),
            "source_run_id": payload.get("source_run_id"),
            "source_run_attempt": payload.get("source_run_attempt"),
            "source_workflow_file": payload.get("source_workflow_file"),
            "source_artifact_name": payload.get("source_artifact_name"),
            "first_noted_at": existing.get("first_noted_at") or _now_iso(),
            "last_checked_at": _now_iso(),
            "operator_action_required": True,
            "diagnostic_summary": diagnostic_summary,
        }
    )
    review_data["deferred_gaps"][source_event_key] = existing


def observer_run_reason_from_details(run_details: dict, runbook_signature: dict | None) -> str:
    status = str(run_details.get("status", "")).strip()
    conclusion = run_details.get("conclusion")
    if runbook_signature and all(run_details.get(key) == value for key, value in runbook_signature.items()):
        return "awaiting_observer_approval"
    if status in {"queued", "in_progress"}:
        return "observer_in_progress"
    if status == "completed":
        if conclusion == "success":
            return "completed_success"
        if conclusion in {"failure", "timed_out", "action_required", "stale"}:
            return "observer_failed"
        if conclusion == "cancelled":
            return "observer_cancelled"
    return "observer_state_unknown"


def can_mark_observer_run_missing(gap: dict, now: datetime | None = None) -> bool:
    now = now or _now()
    created_at = gap.get("source_event_created_at")
    created_dt = parse_timestamp(created_at)
    if created_dt is None or now < created_dt + timedelta(hours=24):
        return False
    return bool(gap.get("full_scan_complete") and gap.get("later_recheck_complete") and not gap.get("correlated_run_found") and not gap.get("approval_pending_evidence_retained"))


def classify_artifact_gap_reason(gap: dict, now: datetime | None = None) -> str:
    now = now or _now()
    retention_days = int(os.environ.get("DEFERRED_ARTIFACT_RETENTION_DAYS", "7"))
    run_created_at = parse_timestamp(gap.get("run_created_at"))
    if gap.get("artifact_seen_at") or gap.get("artifact_last_downloadable_at"):
        return "artifact_expired"
    if run_created_at is not None and gap.get("retention_window_documented") and now >= run_created_at + timedelta(days=retention_days):
        return "artifact_expired"
    if gap.get("artifact_inspection_complete"):
        return "artifact_missing"
    return "observer_state_unknown"


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def handle_workflow_run_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_workflow_run_event")
    if _runtime_epoch(state) != "freshness_v15":
        print("V18 workflow_run reconcile safe-noop before epoch flip")
        return False
    payload = _load_deferred_context()
    pr_number = int(payload.get("pr_number", 0) or 0)
    if pr_number <= 0:
        raise RuntimeError("Deferred context is missing a valid PR number")
    bot.collect_touched_item(pr_number)
    review_data = bot.ensure_review_entry(state, pr_number, create=True)
    if review_data is None:
        raise RuntimeError(f"No review entry available for PR #{pr_number}")
    event_name = payload.get("source_event_name")
    event_action = payload.get("source_event_action")
    source_event_key = str(payload.get("source_event_key", ""))
    try:
        if event_name == "issue_comment":
            _validate_deferred_comment_artifact(payload)
            _validate_workflow_run_artifact_identity(payload)
            if source_event_key != f"issue_comment:{payload['comment_id']}":
                raise RuntimeError("Deferred comment artifact source_event_key mismatch")
            comment_author = str(payload.get("actor_login", ""))
            comment_created_at = str(payload.get("source_created_at"))
            comment_id_value = payload.get("comment_id")
            if not isinstance(comment_id_value, int):
                raise RuntimeError("Deferred comment artifact comment_id must be an integer")
            comment_id = comment_id_value
            classified = payload.get("comment_class")
            source_freshness_eligible = classified in {"plain_text", "command_plus_text"} and bool(payload.get("has_non_command_text"))
            live_comment = bot.github_api("GET", f"issues/comments/{payload['comment_id']}")
            if not isinstance(live_comment, dict):
                changed = False
                if source_freshness_eligible:
                    changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at)
                _update_deferred_gap(review_data, payload, "reconcile_failed_closed", f"Deferred comment {payload['comment_id']} is no longer visible; source-time freshness only may be preserved. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
                return changed
            live_body = live_comment.get("body")
            if not isinstance(live_body, str):
                raise RuntimeError("Live deferred comment body is unavailable")
            if _digest_body(live_body) != payload.get("source_body_digest"):
                changed = False
                if source_freshness_eligible:
                    changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at)
                _update_deferred_gap(review_data, payload, "reconcile_failed_closed", f"Deferred comment {payload['comment_id']} body digest changed; command execution suppressed. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
                return changed
            changed = False
            if source_freshness_eligible:
                changed = _record_conversation_freshness(bot, state, pr_number, comment_author, comment_id, comment_created_at) or changed
            if classified in {"command_only", "command_plus_text"}:
                live_classified = classify_comment_payload(bot, live_body)
                if int(live_classified.get("command_count", 0)) == 1:
                    changed = _handle_command(bot, state, pr_number, comment_author, live_classified) or changed
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return changed

        if event_name == "pull_request_review" and event_action == "submitted":
            _validate_deferred_review_artifact(payload)
            _validate_workflow_run_artifact_identity(payload)
            review_id_value = payload.get("review_id")
            if not isinstance(review_id_value, int):
                raise RuntimeError("Deferred review artifact review_id must be an integer")
            review_id = review_id_value
            if source_event_key != f"pull_request_review:{review_id}":
                raise RuntimeError("Deferred review-submitted artifact source_event_key mismatch")
            live_review = bot.github_api("GET", f"pulls/{pr_number}/reviews/{review_id}")
            live_pr = bot.github_api("GET", f"pulls/{pr_number}")
            if not isinstance(live_pr, dict):
                raise RuntimeError(f"Failed to fetch live PR #{pr_number}")
            live_commit_id = None
            live_submitted_at = payload.get("source_submitted_at")
            live_state = payload.get("source_review_state")
            if isinstance(live_review, dict):
                live_commit_id = live_review.get("commit_id")
                live_submitted_at = live_review.get("submitted_at") or live_submitted_at
                live_state = live_review.get("state") or live_state
            else:
                live_commit_id = payload.get("source_commit_id")
            actor = str(payload.get("actor_login", ""))
            changed = maybe_record_head_observation_repair(bot, pr_number, review_data)
            if isinstance(review_data.get("current_reviewer"), str) and review_data.get("current_reviewer", "").lower() == actor.lower() and isinstance(live_commit_id, str) and isinstance(live_submitted_at, str):
                bot.reviews_module.accept_channel_event(
                    review_data,
                    "reviewer_review",
                    semantic_key=source_event_key,
                    timestamp=live_submitted_at,
                    actor=actor,
                    reviewed_head_sha=live_commit_id,
                    source_precedence=1,
                )
            _record_review_rebuild(bot, state, pr_number, review_data)
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return changed or True

        if event_name == "pull_request_review" and event_action == "dismissed":
            _validate_deferred_review_artifact(payload)
            _validate_workflow_run_artifact_identity(payload)
            review_id_value = payload.get("review_id")
            if not isinstance(review_id_value, int):
                raise RuntimeError("Deferred review artifact review_id must be an integer")
            if source_event_key != f"pull_request_review_dismissed:{review_id_value}":
                raise RuntimeError("Deferred review-dismissed artifact source_event_key mismatch")
            bot.reviews_module.accept_channel_event(
                review_data,
                "review_dismissal",
                semantic_key=source_event_key,
                timestamp=_now_iso(),
                dismissal_only=True,
            )
            maybe_record_head_observation_repair(bot, pr_number, review_data)
            _record_review_rebuild(bot, state, pr_number, review_data)
            _mark_reconciled_source_event(review_data, source_event_key)
            _clear_source_event_key(review_data, source_event_key)
            return True
    except RuntimeError as exc:
        _update_deferred_gap(review_data, payload, "reconcile_failed_closed", f"{exc} See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.")
        raise
    raise RuntimeError("Unsupported deferred workflow_run payload")


def handle_closed_event(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_closed_event")
    issue_number = int(os.environ.get("ISSUE_NUMBER", 0))
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    issue_key = str(issue_number)
    if isinstance(state.get("active_reviews"), dict) and issue_key in state["active_reviews"]:
        del state["active_reviews"][issue_key]
        return True
    return False


def handle_manual_dispatch(bot, state: dict) -> bool:
    action = os.environ.get("MANUAL_ACTION", "")
    if action == "show-state":
        print(f"Current state:\n{yaml.dump(state, default_flow_style=False)}")
        return False
    bot.assert_lock_held("handle_manual_dispatch")
    if action == "sync-members":
        _, changes = bot.sync_members_with_queue(state)
        return bool(changes)
    if action == "repair-review-status-labels":
        for issue_number in bot.list_open_items_with_status_labels():
            bot.collect_touched_item(issue_number)
        return False
    if action == "check-overdue":
        return bot.handle_scheduled_check(state)
    if action == "execute-pending-privileged-command":
        source_event_key = os.environ.get("PRIVILEGED_SOURCE_EVENT_KEY", "").strip()
        if not source_event_key:
            raise RuntimeError("Missing PRIVILEGED_SOURCE_EVENT_KEY for privileged command execution")
        for issue_key, review_data in (state.get("active_reviews") or {}).items():
            if not isinstance(review_data, dict):
                continue
            pending = review_data.get("pending_privileged_commands")
            if not isinstance(pending, dict) or source_event_key not in pending:
                continue
            record = pending[source_event_key]
            if not isinstance(record, dict):
                raise RuntimeError("Pending privileged command record is malformed")
            if record.get("status") != "pending":
                return False
            issue_number = int(record.get("issue_number") or int(issue_key))
            actor = str(record.get("actor", "")).strip()
            command_name = record.get("command_name")
            if command_name != "accept-no-fls-changes":
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso()
                record["result"] = "unsupported_command"
                return True
            issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
            if not isinstance(issue_snapshot, dict) or isinstance(issue_snapshot.get("pull_request"), dict):
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso()
                record["result"] = "live_target_invalid"
                return True
            labels = {
                label.get("name")
                for label in issue_snapshot.get("labels", [])
                if isinstance(label, dict) and isinstance(label.get("name"), str)
            }
            if bot.FLS_AUDIT_LABEL not in labels or not bot.check_user_permission(actor, "triage"):
                record["status"] = "failed_closed"
                record["completed_at"] = _now_iso()
                record["result"] = "live_revalidation_failed"
                return True
            message, success = bot.handle_accept_no_fls_changes_command(issue_number, actor)
            record["completed_at"] = _now_iso()
            record["result_message"] = message
            record["status"] = "executed" if success else "failed_closed"
            return True
        raise RuntimeError(f"Pending privileged command not found for {source_event_key}")
    return False


def _update_observer_watermark(bot, review_data: dict, surface: str, event_time: str, event_id: str) -> None:
    watermarks = review_data.setdefault("observer_discovery_watermarks", {})
    current = watermarks.get(surface) if isinstance(watermarks.get(surface), dict) else {}
    watermarks[surface] = {
        "last_scan_started_at": current.get("last_scan_started_at") or _now_iso(),
        "last_scan_completed_at": _now_iso(),
        "last_safe_event_time": event_time,
        "last_safe_event_id": event_id,
        "lookback_seconds": bot.DEFERRED_DISCOVERY_OVERLAP_SECONDS if hasattr(bot, "DEFERRED_DISCOVERY_OVERLAP_SECONDS") else 3600,
        "bootstrap_window_seconds": bot.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS if hasattr(bot, "DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS") else 604800,
        "bootstrap_completed_at": current.get("bootstrap_completed_at") or _now_iso(),
    }


def _load_surface_watermark(review_data: dict, surface: str) -> dict:
    watermarks = review_data.setdefault("observer_discovery_watermarks", {})
    current = watermarks.get(surface)
    if isinstance(current, dict):
        return current
    current = {
        "last_scan_started_at": None,
        "last_scan_completed_at": None,
        "last_safe_event_time": None,
        "last_safe_event_id": None,
        "lookback_seconds": None,
        "bootstrap_window_seconds": None,
        "bootstrap_completed_at": None,
    }
    watermarks[surface] = current
    return current


def _surface_scan_floor(bot, watermark: dict) -> datetime:
    now = _now()
    bootstrap_floor = now - timedelta(seconds=bot.DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS)
    safe_time = parse_timestamp(watermark.get("last_safe_event_time"))
    if safe_time is None:
        return bootstrap_floor
    return max(bootstrap_floor, safe_time - timedelta(seconds=bot.DEFERRED_DISCOVERY_OVERLAP_SECONDS))


def _list_issue_comments_paginated(bot, issue_number: int) -> tuple[list[dict] | None, bool]:
    comments: list[dict] = []
    page = 1
    while True:
        response = bot.github_api("GET", f"issues/{issue_number}/comments?per_page=100&page={page}")
        if response is None:
            return None, False
        if not isinstance(response, list):
            return None, False
        comments.extend([comment for comment in response if isinstance(comment, dict)])
        if len(response) < 100:
            return comments, True
        page += 1


def _discover_visible_comment_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    watermark = _load_surface_watermark(review_data, "comments")
    watermark["last_scan_started_at"] = _now_iso()
    comments, complete = _list_issue_comments_paginated(bot, issue_number)
    if comments is None:
        return None, False
    floor = _surface_scan_floor(bot, watermark)
    discovered: list[dict] = []
    for comment in comments:
        comment_id = comment.get("id")
        created_at = comment.get("created_at")
        if not isinstance(comment_id, int) or not isinstance(created_at, str):
            continue
        created_dt = parse_timestamp(created_at)
        if created_dt is None or created_dt < floor:
            continue
        discovered.append({
            "source_event_key": f"issue_comment:{comment_id}",
            "source_event_name": "issue_comment",
            "source_event_action": "created",
            "source_created_at": created_at,
            "object_id": str(comment_id),
            "surface": "comments",
        })
    return discovered, complete


def _discover_visible_review_events(bot, issue_number: int, review_data: dict) -> tuple[list[dict] | None, bool]:
    watermark = _load_surface_watermark(review_data, "reviews_submitted")
    watermark["last_scan_started_at"] = _now_iso()
    reviews = bot.get_pull_request_reviews(issue_number)
    if reviews is None:
        return None, False
    floor = _surface_scan_floor(bot, watermark)
    discovered: list[dict] = []
    for review in reviews:
        review_id = review.get("id") if isinstance(review, dict) else None
        submitted_at = review.get("submitted_at") if isinstance(review, dict) else None
        if not isinstance(review_id, int) or not isinstance(submitted_at, str):
            continue
        submitted_dt = parse_timestamp(submitted_at)
        if submitted_dt is None or submitted_dt < floor:
            continue
        discovered.append({
            "source_event_key": f"pull_request_review:{review_id}",
            "source_event_name": "pull_request_review",
            "source_event_action": "submitted",
            "source_created_at": submitted_at,
            "object_id": str(review_id),
            "surface": "reviews_submitted",
        })
    return discovered, True


def _record_gap_diagnostics(
    bot,
    review_data: dict,
    source_event_key: str,
    *,
    source_event_name: str,
    source_event_action: str,
    issue_number: int,
    source_created_at: str,
    workflow_file: str,
    run_correlation: dict,
    run_detail: dict | None,
    artifact_correlation: dict | None,
    reason: str,
    diagnostic_reason: str,
) -> None:
    _update_deferred_gap(
        review_data,
        {
            "source_event_key": source_event_key,
            "source_event_name": source_event_name,
            "source_event_action": source_event_action,
            "pr_number": issue_number,
            "source_created_at": source_created_at,
            "source_workflow_file": workflow_file,
            "source_run_id": run_correlation.get("correlated_run"),
            "source_run_attempt": run_detail.get("run_attempt") if isinstance(run_detail, dict) else None,
            "source_artifact_name": _artifact_expected_name(
                {
                    "source_event_name": source_event_name,
                    "source_event_action": source_event_action,
                    "source_run_id": run_correlation.get("correlated_run") or 0,
                    "source_run_attempt": (run_detail or {}).get("run_attempt") or 0,
                }
            ),
        },
        reason,
        f"Trusted sweeper diagnostics for {source_event_key}: {diagnostic_reason}. See {bot.REVIEW_FRESHNESS_RUNBOOK_PATH}.",
    )
    gap = review_data["deferred_gaps"][source_event_key]
    gap["full_scan_complete"] = bool(run_correlation.get("full_scan_complete"))
    gap["later_recheck_complete"] = bool(run_correlation.get("later_recheck_complete"))
    gap["correlated_run_found"] = bool(run_correlation.get("correlated_run"))
    raw_candidate_run_ids = run_correlation.get("candidate_run_ids")
    if isinstance(raw_candidate_run_ids, list):
        gap["candidate_run_ids"] = raw_candidate_run_ids
    if isinstance(run_detail, dict):
        gap["run_created_at"] = run_detail.get("created_at")
    if isinstance(artifact_correlation, dict):
        prior_visibility = artifact_correlation.get("prior_visibility", {}).get(run_correlation.get("correlated_run"), {})
        if isinstance(prior_visibility, dict):
            gap.update(prior_visibility)


def _should_skip_discovered_key(bot, review_data: dict, source_event_key: str, channels: tuple[str, ...]) -> bool:
    if _was_reconciled_source_event(review_data, source_event_key):
        return True
    if source_event_key in review_data.get("deferred_gaps", {}):
        existing_gap = review_data["deferred_gaps"].get(source_event_key)
        if isinstance(existing_gap, dict) and existing_gap.get("reason") in {
            "awaiting_observer_run",
            "awaiting_observer_approval",
            "observer_in_progress",
            "observer_failed",
            "observer_cancelled",
            "observer_run_missing",
            "observer_state_unknown",
            "artifact_missing",
            "artifact_invalid",
            "artifact_expired",
            "reconcile_failed_closed",
        }:
            return False
    return any(bot.reviews_module._semantic_key_seen(review_data, channel, source_event_key) for channel in channels)


def sweep_deferred_gaps(bot, state: dict) -> bool:
    changed = False
    active_reviews = state.get("active_reviews")
    if not isinstance(active_reviews, dict):
        return False
    for issue_key, review_data in active_reviews.items():
        if not isinstance(review_data, dict):
            continue
        issue_number = int(issue_key)
        pull_request = bot.github_api("GET", f"pulls/{issue_number}")
        if not isinstance(pull_request, dict) or str(pull_request.get("state", "")).lower() != "open":
            continue
        discovered_comments, comments_complete = _discover_visible_comment_events(bot, issue_number, review_data)
        if comments_complete and isinstance(discovered_comments, list):
            for discovered in discovered_comments:
                source_event_key = discovered["source_event_key"]
                created_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_comment", "contributor_comment")):
                    continue
                existing_gap = review_data.get("deferred_gaps", {}).get(source_event_key, {})
                workflow_file = ".github/workflows/reviewer-bot-pr-comment-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "issue_comment")
                run_correlation = correlate_candidate_observer_runs(
                    source_event_key,
                    source_event_kind="issue_comment:created",
                    source_event_created_at=created_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
                )
                run_correlation["later_recheck_complete"] = bool(existing_gap.get("full_scan_complete"))
                artifact_correlation = None
                run_detail = None
                if run_correlation.get("status") == "candidate_runs_found":
                    artifact_correlation = inspect_run_artifact_payloads(
                        bot,
                        run_correlation.get("candidate_runs", []),
                        source_event_key,
                        pr_number=issue_number,
                        source_event_kind="issue_comment:created",
                    )
                    exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
                    if isinstance(exact_run_id, int):
                        run_correlation["correlated_run"] = exact_run_id
                        run_correlation["correlated_run_found"] = True
                        run_detail = _fetch_run_detail(bot, exact_run_id)
                reason, diagnostic_reason = evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": created_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                )
                _record_gap_diagnostics(
                    bot,
                    review_data,
                    source_event_key,
                    source_event_name="issue_comment",
                    source_event_action="created",
                    issue_number=issue_number,
                    source_created_at=created_at,
                    workflow_file=workflow_file,
                    run_correlation=run_correlation,
                    run_detail=run_detail,
                    artifact_correlation=artifact_correlation,
                    reason=reason,
                    diagnostic_reason=diagnostic_reason,
                )
                changed = True
            if discovered_comments:
                last_comment = discovered_comments[-1]
                _update_observer_watermark(bot, review_data, "comments", last_comment["source_created_at"], last_comment["object_id"])
            else:
                watermark = _load_surface_watermark(review_data, "comments")
                watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso()
                watermark["last_scan_completed_at"] = _now_iso()
                watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso()
        discovered_reviews, reviews_complete = _discover_visible_review_events(bot, issue_number, review_data)
        if reviews_complete and isinstance(discovered_reviews, list):
            for discovered in discovered_reviews:
                source_event_key = discovered["source_event_key"]
                submitted_at = discovered["source_created_at"]
                if _should_skip_discovered_key(bot, review_data, source_event_key, ("reviewer_review",)):
                    continue
                existing_gap = review_data.get("deferred_gaps", {}).get(source_event_key, {})
                workflow_file = ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml"
                workflow_runs = _fetch_workflow_runs_for_file(bot, workflow_file, "pull_request_review")
                run_correlation = correlate_candidate_observer_runs(
                    source_event_key,
                    source_event_kind="pull_request_review:submitted",
                    source_event_created_at=submitted_at,
                    pr_number=issue_number,
                    workflow_file=workflow_file,
                    workflow_runs=workflow_runs,
                )
                run_correlation["later_recheck_complete"] = bool(existing_gap.get("full_scan_complete"))
                artifact_correlation = None
                run_detail = None
                if run_correlation.get("status") == "candidate_runs_found":
                    artifact_correlation = inspect_run_artifact_payloads(
                        bot,
                        run_correlation.get("candidate_runs", []),
                        source_event_key,
                        pr_number=issue_number,
                        source_event_kind="pull_request_review:submitted",
                    )
                    exact_run_id = artifact_correlation.get("correlated_run") if isinstance(artifact_correlation, dict) else None
                    if isinstance(exact_run_id, int):
                        run_correlation["correlated_run"] = exact_run_id
                        run_correlation["correlated_run_found"] = True
                        run_detail = _fetch_run_detail(bot, exact_run_id)
                reason, diagnostic_reason = evaluate_deferred_gap_state(
                    {
                        **existing_gap,
                        "source_event_created_at": submitted_at,
                    },
                    run_correlation,
                    run_detail,
                    artifact_correlation,
                )
                _record_gap_diagnostics(
                    bot,
                    review_data,
                    source_event_key,
                    source_event_name="pull_request_review",
                    source_event_action="submitted",
                    issue_number=issue_number,
                    source_created_at=submitted_at,
                    workflow_file=workflow_file,
                    run_correlation=run_correlation,
                    run_detail=run_detail,
                    artifact_correlation=artifact_correlation,
                    reason=reason,
                    diagnostic_reason=diagnostic_reason,
                )
                changed = True
            if discovered_reviews:
                last_review = discovered_reviews[-1]
                _update_observer_watermark(bot, review_data, "reviews_submitted", last_review["source_created_at"], last_review["object_id"])
            else:
                watermark = _load_surface_watermark(review_data, "reviews_submitted")
                watermark["last_scan_started_at"] = watermark.get("last_scan_started_at") or _now_iso()
                watermark["last_scan_completed_at"] = _now_iso()
                watermark["bootstrap_completed_at"] = watermark.get("bootstrap_completed_at") or _now_iso()
    return changed


def handle_scheduled_check(bot, state: dict) -> bool:
    bot.assert_lock_held("handle_scheduled_check")
    changed = sweep_deferred_gaps(bot, state)
    active_reviews = state.get("active_reviews")
    if isinstance(active_reviews, dict):
        for issue_key, review_data in active_reviews.items():
            if not isinstance(review_data, dict) or not review_data.get("current_reviewer"):
                continue
            issue_number = int(issue_key)
            issue_snapshot = bot.get_issue_or_pr_snapshot(issue_number)
            if not isinstance(issue_snapshot, dict) or not isinstance(issue_snapshot.get("pull_request"), dict):
                continue
            if maybe_record_head_observation_repair(bot, issue_number, review_data):
                changed = True
    overdue_reviews = bot.check_overdue_reviews(state)
    if not overdue_reviews:
        return changed
    for review in overdue_reviews:
        issue_number = review["issue_number"]
        reviewer = review["reviewer"]
        if review["needs_warning"]:
            if bot.handle_overdue_review_warning(state, issue_number, reviewer):
                changed = True
        elif review["needs_transition"]:
            bot.handle_transition_notice(state, issue_number, reviewer)
            changed = True
    return changed
