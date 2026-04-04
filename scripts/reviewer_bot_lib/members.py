"""Reviewer queue membership helpers."""

from .config import MEMBERS_URL


def _log(bot, level: str, message: str, **fields) -> None:
    bot.logger.event(level, message, **fields)


def fetch_members(bot) -> list[dict]:
    """Fetch and parse members.md from the consortium repo to extract Producers."""
    try:
        response = bot.rest_transport.request("GET", MEMBERS_URL, timeout_seconds=10)
        if getattr(response, "status_code", 0) >= 400:
            raise RuntimeError(f"status {response.status_code}")
        content = response.text
    except Exception as exc:
        _log(bot, "warning", f"Failed to fetch members file from {MEMBERS_URL}: {exc}", url=MEMBERS_URL, error=str(exc))
        return []

    producers = []
    lines = content.split("\n")
    in_table = False
    headers = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith("|") and line.endswith("|"):
            cells = [cell.strip() for cell in line.split("|")[1:-1]]

            if not in_table and "Member Name" in cells:
                headers = [header.lower().replace(" ", "_") for header in cells]
                in_table = True
                continue

            if in_table and all(cell.replace("-", "").replace(":", "") == "" for cell in cells):
                continue

            if in_table and len(cells) == len(headers):
                row = dict(zip(headers, cells))
                role = row.get("role", "").strip()
                if "Producer" in role:
                    github_username = row.get("github_username", "").strip()
                    if github_username.startswith("@"):
                        github_username = github_username[1:]

                    if github_username:
                        producers.append(
                            {
                                "github": github_username,
                                "name": row.get("member_name", "").strip(),
                            }
                        )

    return producers
