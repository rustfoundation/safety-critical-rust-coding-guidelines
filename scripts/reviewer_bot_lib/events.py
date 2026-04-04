"""Reviewer-bot event, deferred-evidence, and freshness handlers."""

from __future__ import annotations


def _log(bot, level: str, message: str, **fields) -> None:
    logger = getattr(bot, "logger", None)
    if logger is not None and hasattr(logger, "event"):
        logger.event(level, message, **fields)
        return
    stream = __import__("sys").stderr if level in {"warning", "error"} else __import__("sys").stdout
    stream.write(f"{message}\n")


def _runtime_epoch(state: dict) -> str:
    return str(state.get("freshness_runtime_epoch", "")).strip() or "legacy_v14"


def _is_pr_event(bot) -> bool:
    return bot.get_config_value("IS_PULL_REQUEST", "false").lower() == "true"


def _require_v18_for_pr(bot, state: dict, context: str) -> bool:
    if not _is_pr_event(bot):
        return True
    epoch = _runtime_epoch(state)
    if epoch != "freshness_v15":
        _log(bot, "info", f"V18 PR freshness path safe-noop for {context}; epoch is {epoch}", context=context, runtime_epoch=epoch)
        return False
    return True


def _require_legacy_for_legacy_pr(bot, state: dict, context: str) -> bool:
    if not _is_pr_event(bot):
        return True
    epoch = _runtime_epoch(state)
    if epoch == "freshness_v15":
        _log(bot, "info", f"Legacy PR freshness path safe-noop for {context}; epoch is {epoch}", context=context, runtime_epoch=epoch)
        return False
    return True


def handle_pull_request_review_event(bot, state: dict) -> bool:
    issue_number = int(bot.get_config_value("ISSUE_NUMBER", "0") or 0)
    if not issue_number:
        return False
    bot.collect_touched_item(issue_number)
    if _runtime_epoch(state) == "freshness_v15":
        _log(bot, "info", "Legacy direct pull_request_review mutation disabled after epoch flip", issue_number=issue_number)
        return False
    review_action = bot.get_config_value("EVENT_ACTION", "").strip().lower()
    if review_action not in {"submitted", "dismissed"}:
        return False
    _log(bot, "info", f"Deferring pull_request_review {review_action} for #{issue_number}", issue_number=issue_number, review_action=review_action)
    return False
