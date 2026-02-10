# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from __future__ import annotations

import tempfile
from typing import Any


def extract_paragraphs(data: dict[str, Any]) -> dict[str, dict[str, str]]:
    paragraphs: dict[str, dict[str, str]] = {}

    for document in data.get("documents", []):
        document_title = document.get("title", "")
        for section in document.get("sections", []):
            section_title = section.get("title", "")
            for paragraph in section.get("paragraphs", []):
                paragraph_id = paragraph.get("id", "")
                if not paragraph_id or not paragraph_id.startswith("fls_"):
                    continue

                paragraphs[paragraph_id] = {
                    "checksum": paragraph.get("checksum", ""),
                    "section_id": paragraph.get("number", ""),
                    "link": paragraph.get("link", ""),
                    "document_title": document_title,
                    "section_title": section_title,
                }

    return paragraphs


def diff_paragraphs(
    live_paragraphs: dict[str, dict[str, str]],
    locked_paragraphs: dict[str, dict[str, str]],
) -> dict[str, list[dict[str, Any]]]:
    added_ids = sorted(set(live_paragraphs.keys()) - set(locked_paragraphs.keys()))
    removed_ids = sorted(
        set(locked_paragraphs.keys()) - set(live_paragraphs.keys())
    )
    common_ids = sorted(
        set(live_paragraphs.keys()) & set(locked_paragraphs.keys())
    )

    added = [
        {"fls_id": fls_id, "live": live_paragraphs[fls_id]}
        for fls_id in added_ids
    ]
    removed = [
        {"fls_id": fls_id, "locked": locked_paragraphs[fls_id]}
        for fls_id in removed_ids
    ]

    changed: list[dict[str, Any]] = []
    for fls_id in common_ids:
        live_entry = live_paragraphs[fls_id]
        locked_entry = locked_paragraphs[fls_id]
        content_changed = live_entry.get("checksum") != locked_entry.get("checksum")
        section_changed = live_entry.get("section_id") != locked_entry.get("section_id")

        if content_changed or section_changed:
            changed.append(
                {
                    "fls_id": fls_id,
                    "live": live_entry,
                    "locked": locked_entry,
                    "content_changed": content_changed,
                    "section_changed": section_changed,
                }
            )

    return {"added": added, "removed": removed, "changed": changed}


def has_differences(diff: dict[str, list[dict[str, Any]]]) -> bool:
    return bool(diff.get("added") or diff.get("removed") or diff.get("changed"))


def build_detailed_differences(
    diff: dict[str, list[dict[str, Any]]],
    fls_to_guidelines: dict[str, list[dict[str, str]]],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    detailed_differences: list[str] = []
    affected_guidelines: dict[str, dict[str, Any]] = {}

    def format_affected_guidelines(fls_id: str) -> str:
        affected = fls_to_guidelines.get(fls_id, [])
        if not affected:
            return "    No guidelines affected"

        result = []
        for guideline in affected:
            guideline_id = guideline.get("id") or "unknown"
            title = guideline.get("title") or "Untitled"
            result.append(f"    - {guideline_id}: {title}")
        return "\n".join(result)

    def track_affected_guidelines(
        fls_id: str,
        change_type: str,
        section_id: str,
    ) -> None:
        for guideline in fls_to_guidelines.get(fls_id, []):
            guideline_id = guideline.get("id") or "unknown"
            title = guideline.get("title") or "Untitled"
            if guideline_id not in affected_guidelines:
                affected_guidelines[guideline_id] = {
                    "title": title,
                    "changes": [],
                }
            affected_guidelines[guideline_id]["changes"].append(
                {
                    "fls_id": fls_id,
                    "change_type": change_type,
                    "section_id": section_id,
                }
            )

    for entry in diff.get("added", []):
        fls_id = entry["fls_id"]
        section_id = entry["live"].get("section_id", "")
        diff_msg = f"New FLS ID added: {fls_id} ({section_id})"
        affected_msg = format_affected_guidelines(fls_id)
        detailed_differences.append(
            f"{diff_msg}\n  Affected guidelines:\n{affected_msg}"
        )
        track_affected_guidelines(fls_id, "added", section_id)

    for entry in diff.get("removed", []):
        fls_id = entry["fls_id"]
        section_id = entry["locked"].get("section_id", "")
        diff_msg = f"FLS ID removed: {fls_id} ({section_id})"
        affected_msg = format_affected_guidelines(fls_id)
        detailed_differences.append(
            f"{diff_msg}\n  Affected guidelines:\n{affected_msg}"
        )
        track_affected_guidelines(fls_id, "removed", section_id)

    for entry in diff.get("changed", []):
        fls_id = entry["fls_id"]
        live_entry = entry["live"]
        locked_entry = entry["locked"]

        changes: list[str] = []
        change_type = None

        if entry.get("content_changed"):
            live_checksum = live_entry.get("checksum", "")
            locked_checksum = locked_entry.get("checksum", "")
            live_section = live_entry.get("section_id", "")
            changes.append(
                f"Content changed for FLS ID {fls_id} ({live_section}): "
                + f"checksum was {locked_checksum[:8]}... now {live_checksum[:8]}..."
            )
            change_type = "content_changed"

        if entry.get("section_changed"):
            live_section = live_entry.get("section_id", "")
            locked_section = locked_entry.get("section_id", "")
            changes.append(
                f"Section changed for FLS ID {fls_id}: {locked_section} -> {live_section}"
            )
            if change_type is None:
                change_type = "section_changed"

        if changes:
            affected_msg = format_affected_guidelines(fls_id)
            detailed_differences.append(
                f"{changes[0]}\n  Affected guidelines:\n{affected_msg}"
            )

            for change in changes[1:]:
                detailed_differences.append(change)

            if change_type:
                section_id = live_entry.get("section_id") or locked_entry.get(
                    "section_id", ""
                )
                track_affected_guidelines(fls_id, change_type, section_id)

    if affected_guidelines:
        detailed_differences.append("\n\nDETAILED AFFECTED GUIDELINES:")
        for guideline_id, info in sorted(affected_guidelines.items()):
            changed_fls = [
                f"{change['fls_id']} ({change['section_id']})"
                for change in info["changes"]
            ]
            detailed_differences.append(f"{guideline_id}: {info['title']}")
            detailed_differences.append(
                f"  Changed FLS paragraphs: {', '.join(changed_fls)}"
            )

    return detailed_differences, affected_guidelines


def build_summary(
    affected_guidelines: dict[str, dict[str, Any]],
    has_differences_flag: bool,
) -> list[str]:
    if not has_differences_flag:
        return []

    summary = [
        "Found differences between live FLS data and lock file "
        f"affecting {len(affected_guidelines)} guidelines"
    ]
    for guideline_id, info in sorted(affected_guidelines.items()):
        fls_ids = sorted({change["fls_id"] for change in info["changes"]})
        summary.append(f"{guideline_id}: {', '.join(fls_ids)}")

    return summary


def write_detailed_report(
    detailed_differences: list[str],
    prefix: str = "fls_diff_",
    suffix: str = ".txt",
) -> str:
    with tempfile.NamedTemporaryFile(
        mode="w",
        delete=False,
        prefix=prefix,
        suffix=suffix,
    ) as temp_file:
        temp_file.write("\n".join(detailed_differences))
        return temp_file.name
