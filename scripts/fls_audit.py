#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Audit changes between live FLS paragraph IDs and src/spec.lock.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from coding_guidelines import fls_diff


DEFAULT_FLS_URL = "https://rust-lang.github.io/fls/paragraph-ids.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit changes between live FLS data and src/spec.lock."
    )
    parser.add_argument(
        "--output-dir",
        default="build/fls_audit",
        help="Directory for report outputs (default: build/fls_audit)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print a summary and skip writing report files",
    )
    parser.add_argument(
        "--fail-on-impact",
        action="store_true",
        help="Exit non-zero if any guidelines are affected",
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        help="Path to a paragraph-ids.json file for offline comparison",
    )
    return parser.parse_args()


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def scan_guideline_references(
    src_dir: Path,
    repo_root: Path,
) -> dict[str, list[dict[str, str]]]:
    fls_to_guidelines: dict[str, list[dict[str, str]]] = {}

    file_paths = set(src_dir.rglob("*.rst"))
    file_paths.update(src_dir.rglob("*.rst.inc"))

    for path in sorted(file_paths):
        collect_guidelines_from_file(path, repo_root, fls_to_guidelines)

    return fls_to_guidelines


def collect_guidelines_from_file(
    path: Path,
    repo_root: Path,
    fls_to_guidelines: dict[str, list[dict[str, str]]],
) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    current: dict[str, Any] | None = None

    def flush_current() -> None:
        nonlocal current
        if not current or not current["fls_ids"]:
            current = None
            return

        guideline_id = current.get("id") or "unknown"
        title = current.get("title") or "Untitled"
        rel_path = str(path.relative_to(repo_root))

        for fls_id in sorted(current["fls_ids"]):
            fls_to_guidelines.setdefault(fls_id, []).append(
                {
                    "id": guideline_id,
                    "title": title,
                    "file": rel_path,
                }
            )

        current = None

    for line in lines:
        stripped = line.lstrip()

        if current and line.strip() and not line.startswith((" ", "\t")):
            flush_current()

        if stripped.startswith(".. guideline::"):
            if current:
                flush_current()
            title = stripped[len(".. guideline::") :].strip() or "Untitled"
            current = {"id": None, "title": title, "fls_ids": set()}
            continue

        if not current:
            continue

        if stripped.startswith(":id:"):
            current["id"] = stripped[len(":id:") :].strip()
        elif stripped.startswith(":fls:"):
            fls_id = stripped[len(":fls:") :].strip()
            if fls_id:
                current["fls_ids"].add(fls_id)

    if current:
        flush_current()


def summarize_counts(diff: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    added = len(diff.get("added", []))
    removed = len(diff.get("removed", []))
    content_changed = sum(
        1 for entry in diff.get("changed", []) if entry.get("content_changed")
    )
    section_changed = sum(
        1 for entry in diff.get("changed", []) if entry.get("section_changed")
    )
    return {
        "added": added,
        "removed": removed,
        "content_changed": content_changed,
        "section_changed": section_changed,
    }


def build_markdown_report(
    diff: dict[str, list[dict[str, Any]]],
    affected_guidelines: dict[str, dict[str, Any]],
    guideline_files: dict[str, str],
    detailed_lines: list[str],
    counts: dict[str, int],
    spec_lock_path: Path,
    live_source: str,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []

    lines.append("# FLS Spec Lock Audit Report")
    lines.append("")
    lines.append(f"- Generated: {generated_at}")
    lines.append(f"- Spec lock: `{spec_lock_path}`")
    lines.append(f"- FLS source: `{live_source}`")
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Added IDs: {counts['added']}")
    lines.append(f"- Removed IDs: {counts['removed']}")
    lines.append(f"- Content changed: {counts['content_changed']}")
    lines.append(f"- Section renumbered: {counts['section_changed']}")
    lines.append(f"- Guidelines affected: {len(affected_guidelines)}")
    lines.append("")

    lines.append("## Affected Guidelines")
    if not affected_guidelines:
        lines.append("- None")
    else:
        for guideline_id, info in sorted(affected_guidelines.items()):
            fls_ids = sorted({change["fls_id"] for change in info["changes"]})
            file_path = guideline_files.get(guideline_id)
            file_hint = f" (`{file_path}`)" if file_path else ""
            lines.append(
                f"- {guideline_id}: {info['title']}{file_hint} (FLS: {', '.join(fls_ids)})"
            )
    lines.append("")

    lines.append("## Detailed Differences")
    lines.append("```")
    lines.extend(detailed_lines or ["No differences detected."])
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def resolve_output_dir(repo_root: Path, output_dir: str) -> Path:
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = repo_root / output_path
    return output_path


def main() -> int:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    spec_lock_path = repo_root / "src" / "spec.lock"

    try:
        locked_data = load_json_file(spec_lock_path)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.snapshot:
        try:
            live_data = load_json_file(args.snapshot)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        live_source = str(args.snapshot)
    else:
        try:
            live_data = fetch_json(DEFAULT_FLS_URL)
        except requests.RequestException as exc:
            print(f"Failed to fetch {DEFAULT_FLS_URL}: {exc}", file=sys.stderr)
            return 1
        live_source = DEFAULT_FLS_URL

    fls_to_guidelines = scan_guideline_references(repo_root / "src", repo_root)
    guideline_files = {}
    for guidelines in fls_to_guidelines.values():
        for guideline in guidelines:
            guideline_id = guideline.get("id")
            file_path = guideline.get("file")
            if guideline_id and file_path and guideline_id not in guideline_files:
                guideline_files[guideline_id] = file_path

    live_paragraphs = fls_diff.extract_paragraphs(live_data)
    locked_paragraphs = fls_diff.extract_paragraphs(locked_data)
    diff = fls_diff.diff_paragraphs(live_paragraphs, locked_paragraphs)
    detailed_lines, affected_guidelines = fls_diff.build_detailed_differences(
        diff, fls_to_guidelines
    )
    counts = summarize_counts(diff)

    if args.summary_only:
        print("FLS spec lock audit summary")
        print(f"Added IDs: {counts['added']}")
        print(f"Removed IDs: {counts['removed']}")
        print(f"Content changed: {counts['content_changed']}")
        print(f"Section renumbered: {counts['section_changed']}")
        print(f"Guidelines affected: {len(affected_guidelines)}")
        if affected_guidelines:
            for guideline_id, info in sorted(affected_guidelines.items()):
                fls_ids = sorted({change["fls_id"] for change in info["changes"]})
                print(f"{guideline_id}: {', '.join(fls_ids)}")
        if args.fail_on_impact and affected_guidelines:
            return 2
        return 0

    output_dir = resolve_output_dir(repo_root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spec_lock": str(spec_lock_path),
            "fls_source": live_source,
        },
        "summary": {
            "added": counts["added"],
            "removed": counts["removed"],
            "content_changed": counts["content_changed"],
            "section_changed": counts["section_changed"],
            "affected_guidelines": len(affected_guidelines),
        },
        "changes": diff,
        "affected_guidelines": affected_guidelines,
        "detailed_lines": detailed_lines,
    }

    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )

    markdown_report = build_markdown_report(
        diff,
        affected_guidelines,
        guideline_files,
        detailed_lines,
        counts,
        spec_lock_path,
        live_source,
    )
    markdown_path = output_dir / "report.md"
    markdown_path.write_text(markdown_report, encoding="utf-8")

    print(f"Wrote report: {markdown_path}")
    print(f"Wrote report: {report_path}")

    if args.fail_on_impact and affected_guidelines:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
