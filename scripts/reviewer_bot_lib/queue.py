"""Reviewer queue and assignment helpers."""
from datetime import datetime, timezone

from .config import MAX_RECENT_ASSIGNMENTS


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def sync_members_with_queue(bot, state: dict) -> tuple[dict, list[str]]:
    """Sync the queue with the current members list."""
    fetch_result = bot.adapters.workflow.fetch_members()
    if not fetch_result.ok:
        _log(
            bot,
            "warning",
            "Failed to refresh members; keeping existing queue membership unchanged.",
            failure_kind=fetch_result.failure_kind,
        )
        return state, []
    producers = fetch_result.producers
    current_queue = {member["github"]: member for member in state["queue"]}
    pass_until_users = {member["github"] for member in state.get("pass_until", [])}

    changes = []

    for producer in producers:
        github = producer["github"]
        if github not in current_queue and github not in pass_until_users:
            state["queue"].append(producer)
            changes.append(f"Added {github} to queue")

    current_producer_usernames = {producer["github"] for producer in producers}
    state["queue"] = [
        member for member in state["queue"] if member["github"] in current_producer_usernames
    ]

    removed_from_queue = [
        member["github"]
        for member in current_queue.values()
        if member["github"] not in current_producer_usernames
    ]
    for username in removed_from_queue:
        changes.append(f"Removed {username} from queue (no longer a Producer)")

    producer_names = {producer["github"]: producer["name"] for producer in producers}
    for member in state["queue"]:
        if member["github"] in producer_names:
            member["name"] = producer_names[member["github"]]

    if state["queue"]:
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0

    return state, changes


def reposition_member_as_next(state: dict, username: str) -> bool:
    """Move a queue member to current_index so they are next up."""
    user_index = None
    user_entry = None
    for index, member in enumerate(state["queue"]):
        if member["github"].lower() == username.lower():
            user_index = index
            user_entry = member
            break

    if user_entry is None or user_index is None:
        return False

    state["queue"].pop(user_index)

    if user_index < state["current_index"]:
        state["current_index"] -= 1

    if state["queue"]:
        state["current_index"] = state["current_index"] % len(state["queue"])
    else:
        state["current_index"] = 0

    state["queue"].insert(state["current_index"], user_entry)
    return True


def process_pass_until_expirations(state: dict) -> tuple[dict, list[str]]:
    """Restore pass-until entries whose return date has passed."""
    now = datetime.now(timezone.utc).date()
    restored = []
    still_away = []

    for entry in state.get("pass_until", []):
        return_date = entry.get("return_date")
        if return_date:
            if isinstance(return_date, str):
                try:
                    return_date = datetime.strptime(return_date, "%Y-%m-%d").date()
                except ValueError:
                    still_away.append(entry)
                    continue
            elif isinstance(return_date, datetime):
                return_date = return_date.date()
            else:
                still_away.append(entry)
                continue

            if return_date <= now:
                restored_member = {
                    "github": entry["github"],
                    "name": entry.get("name", entry["github"]),
                }
                state["queue"].append(restored_member)
                reposition_member_as_next(state, entry["github"])
                restored.append(entry["github"])
            else:
                still_away.append(entry)
        else:
            still_away.append(entry)

    state["pass_until"] = still_away
    return state, restored


def get_next_reviewer(state: dict, skip_usernames: set[str] | None = None) -> str | None:
    """Get the next reviewer from the queue using round-robin."""
    if not state["queue"]:
        return None

    skip_usernames = skip_usernames or set()
    queue_size = len(state["queue"])
    start_index = state["current_index"]

    for offset in range(queue_size):
        index = (start_index + offset) % queue_size
        candidate = state["queue"][index]

        if candidate["github"] not in skip_usernames:
            state["current_index"] = (index + 1) % queue_size
            return candidate["github"]

    return None


def record_assignment(
    state: dict,
    github: str,
    issue_number: int,
    issue_type: str,
    *,
    max_recent_assignments: int = MAX_RECENT_ASSIGNMENTS,
) -> None:
    """Record an assignment in the recent_assignments list."""
    assignment = {
        "github": github,
        "issue_number": issue_number,
        "type": issue_type,
        "assigned_at": datetime.now(timezone.utc).isoformat(),
    }

    state["recent_assignments"].insert(0, assignment)
    state["recent_assignments"] = state["recent_assignments"][:max_recent_assignments]
