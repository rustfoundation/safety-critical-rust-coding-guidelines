"""Reviewer-bot event, deferred-evidence, and freshness handlers."""

from __future__ import annotations

import os


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
