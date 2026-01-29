#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""Audit changes between live FLS paragraph IDs and src/spec.lock."""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
from coding_guidelines import fls_diff

from scripts.common import delta_diff, fls_repo, fls_rst

DEFAULT_FLS_URL = "https://rust-lang.github.io/fls/paragraph-ids.json"
DEFAULT_SNAPSHOT_DIR = "build/fls_audit/snapshots"
DEFAULT_CACHE_DIR = ".cache/fls-audit"
PAGES_DEPLOYMENTS_URL = "https://api.github.com/repos/rust-lang/fls/deployments"

ORDERING_DIRECTIVE_RE = re.compile(r"^\s*\.\.\s+(toctree|appendices)::\s*$", re.IGNORECASE)
OPTION_LINE_RE = re.compile(r"^\s*:[^:]+:\s*$")
GLOB_CHARS = {"*", "?", "["}


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
        "--print-diffs",
        action="store_true",
        help="Print colored diffs to stdout when available",
    )
    parser.add_argument(
        "--delta-path",
        type=Path,
        help="Path to a delta binary for colored diff output",
    )
    parser.add_argument(
        "--no-delta",
        action="store_true",
        help="Disable delta usage and skip downloads",
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
    parser.add_argument(
        "--baseline-text-snapshot",
        type=Path,
        help="Path to a prior text snapshot for before/after diffs",
    )
    parser.add_argument(
        "--write-text-snapshot",
        type=Path,
        help="Write a text snapshot for the current FLS commit",
    )
    parser.add_argument(
        "--baseline-fls-commit",
        help="FLS commit to use as the baseline for before text",
    )
    parser.add_argument(
        "--current-fls-commit",
        help="FLS commit to use as the current text source",
    )
    parser.add_argument(
        "--baseline-deployment-offset",
        type=int,
        default=1,
        help="Use the Nth prior deployment as baseline (default: 1)",
    )
    parser.add_argument(
        "--current-deployment-offset",
        type=int,
        default=0,
        help="Use the Nth prior deployment as current (default: 0)",
    )
    parser.add_argument(
        "--fls-repo-cache-dir",
        default=DEFAULT_CACHE_DIR,
        help="Cache directory for the FLS repo (default: .cache/fls-audit)",
    )
    parser.add_argument(
        "--include-legacy-report",
        action="store_true",
        help="Include legacy diff output in Markdown and JSON",
    )
    parser.add_argument(
        "--include-heuristic-details",
        action="store_true",
        help="Include heuristic top-match details in the report",
    )
    return parser.parse_args()


def load_json_file(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc


def fetch_json(url: str, session: requests.Session) -> dict[str, Any]:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def list_changed_rst_files(
    repo_dir: Path, baseline_commit: str, current_commit: str
) -> set[Path]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo_dir),
            "diff",
            "--name-only",
            f"{baseline_commit}..{current_commit}",
            "--",
            "src",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    changed: set[Path] = set()
    for line in result.stdout.splitlines():
        path = Path(line.strip())
        if not path.parts or path.suffix != ".rst":
            continue
        if path.parts[0] != "src":
            continue
        changed.add(Path(*path.parts[1:]))
    return changed


def has_glob_chars(value: str) -> bool:
    return any(char in value for char in GLOB_CHARS)


def file_has_ordering_directive(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return any(ORDERING_DIRECTIVE_RE.match(line) for line in text.splitlines())


def find_ordering_files(src_dir: Path) -> set[Path]:
    ordering_files: set[Path] = set()
    for path in src_dir.rglob("*.rst"):
        if file_has_ordering_directive(path):
            ordering_files.add(path)
    return ordering_files


def parse_ordering_entries(path: Path) -> list[tuple[str, bool]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[tuple[str, bool]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not ORDERING_DIRECTIVE_RE.match(line):
            index += 1
            continue
        indent = len(line) - len(line.lstrip())
        glob_enabled = False
        index += 1
        while index < len(lines):
            current = lines[index]
            if not current.strip():
                index += 1
                continue
            current_indent = len(current) - len(current.lstrip())
            if current_indent <= indent:
                break
            stripped = current.strip()
            if OPTION_LINE_RE.match(stripped):
                if stripped.lower() == ":glob:":
                    glob_enabled = True
                index += 1
                continue
            if stripped.startswith(".."):
                index += 1
                continue
            entries.append((stripped, glob_enabled))
            index += 1
        continue
    return entries


def resolve_ordering_entries(
    ordering_file: Path, src_dir: Path
) -> set[Path]:
    entries = parse_ordering_entries(ordering_file)
    resolved: set[Path] = set()
    base_dir = ordering_file.parent
    for entry, glob_enabled in entries:
        candidate = entry.strip()
        if not candidate:
            continue
        if "://" in candidate:
            continue
        if candidate == "self":
            continue
        entry_base = base_dir
        if candidate.startswith("/"):
            entry_base = src_dir
            candidate = candidate.lstrip("/")
        if glob_enabled or has_glob_chars(candidate):
            pattern = candidate
            if pattern.endswith("/"):
                pattern += "*.rst"
            elif not pattern.endswith(".rst"):
                pattern += ".rst"
            resolved.update(
                path for path in entry_base.glob(pattern) if path.is_file()
            )
            continue
        if not candidate.endswith(".rst"):
            candidate += ".rst"
        path = entry_base / candidate
        if path.exists():
            resolved.add(path)
    return resolved


def resolve_parse_paths(
    repo_dir: Path,
    baseline_worktree: Path,
    current_worktree: Path,
    baseline_commit: str,
    current_commit: str,
) -> tuple[set[Path], set[Path]]:
    changed_rst = list_changed_rst_files(repo_dir, baseline_commit, current_commit)
    baseline_src = baseline_worktree / "src"
    current_src = current_worktree / "src"

    baseline_parse = {baseline_src / path for path in changed_rst}
    current_parse = {current_src / path for path in changed_rst}

    ordering_files_baseline = {
        path.relative_to(baseline_src) for path in find_ordering_files(baseline_src)
    }
    ordering_files_current = {
        path.relative_to(current_src) for path in find_ordering_files(current_src)
    }
    ordering_changed = changed_rst & (ordering_files_baseline | ordering_files_current)

    for relative_path in ordering_changed:
        baseline_file = baseline_src / relative_path
        current_file = current_src / relative_path
        if baseline_file.exists():
            baseline_parse.update(resolve_ordering_entries(baseline_file, baseline_src))
        if current_file.exists():
            current_parse.update(resolve_ordering_entries(current_file, current_src))

    return baseline_parse, current_parse


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    return headers


def fetch_pages_deployments(
    session: requests.Session,
    per_page: int = 10,
) -> list[dict[str, Any]]:
    response = session.get(
        PAGES_DEPLOYMENTS_URL,
        headers=github_headers(),
        params={"environment": "github-pages", "per_page": str(per_page)},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def fetch_deployment_status(
    session: requests.Session,
    statuses_url: str,
) -> dict[str, Any] | None:
    if not statuses_url:
        return None
    response = session.get(
        f"{statuses_url}?per_page=1",
        headers=github_headers(),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, list) and data:
        return data[0]
    return None


def select_pages_deployment(
    session: requests.Session,
    offset: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if offset < 0:
        raise RuntimeError("Deployment offset must be >= 0")
    deployments = fetch_pages_deployments(session, per_page=max(10, offset + 1))
    if not deployments:
        raise RuntimeError("No deployments available")
    successful: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for deployment in deployments:
        status = fetch_deployment_status(
            session, deployment.get("statuses_url", "")
        )
        if status and status.get("state") == "success":
            successful.append((deployment, status))
            if len(successful) > offset:
                return successful[offset]
    if offset >= len(deployments):
        raise RuntimeError(
            f"Requested deployment offset {offset} but only {len(deployments)} deployments available"
        )
    deployment = deployments[offset]
    status = fetch_deployment_status(session, deployment.get("statuses_url", ""))
    return deployment, status


def resolve_deployment_commit(session: requests.Session, offset: int) -> str:
    deployment, _status = select_pages_deployment(session, offset)
    commit = deployment.get("sha")
    if not commit:
        raise RuntimeError("Deployment did not include a commit SHA.")
    return commit


def resolve_output_dir(repo_root: Path, output_dir: str) -> Path:
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = repo_root / output_path
    return output_path


def resolve_snapshot_path(repo_root: Path, snapshot_path: Path) -> Path:
    if snapshot_path.is_absolute():
        return snapshot_path
    return repo_root / snapshot_path


def resolve_snapshot_output(repo_root: Path, snapshot_path: Path) -> Path:
    output_path = resolve_snapshot_path(repo_root, snapshot_path)
    if output_path.exists() and output_path.is_dir():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return output_path / f"fls_text_snapshot_{timestamp}.json"
    if output_path.suffix:
        return output_path
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return output_path / f"fls_text_snapshot_{timestamp}.json"


def resolve_cache_dir(repo_root: Path, cache_dir: str) -> Path:
    cache_path = Path(cache_dir)
    if not cache_path.is_absolute():
        cache_path = repo_root / cache_path
    return cache_path


def load_spec_lock_metadata(spec_lock_path: Path) -> dict[str, Any]:
    try:
        data = load_json_file(spec_lock_path)
    except RuntimeError:
        return {}
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    return {}


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


def parse_section_id(section_id: str) -> tuple[str | None, str | None]:
    if not section_id:
        return None, None
    section = section_id.split(":", 1)[0]
    chapter = section.split(".", 1)[0] if section else None
    return section, chapter


def extract_keywords(text: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "that",
        "with",
        "from",
        "this",
        "then",
        "when",
        "than",
        "where",
        "which",
        "shall",
        "must",
        "should",
        "may",
        "not",
        "only",
        "into",
        "such",
        "used",
        "use",
        "are",
        "is",
        "be",
        "for",
        "any",
        "all",
        "each",
        "set",
        "same",
        "two",
        "one",
        "also",
        "see",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+", text.lower())
    return {word for word in words if len(word) >= 4 and word not in stopwords}


def contains_normative_language(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in ("shall", "must", "required", "shall not", "must not")
    )


def build_guideline_text_index(
    repo_root: Path,
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    file_paths = set((repo_root / "src").rglob("*.rst"))
    file_paths.update((repo_root / "src").rglob("*.rst.inc"))

    current_id: str | None = None
    current_title = ""
    current_tags = ""
    current_text: list[str] = []

    def flush_current() -> None:
        nonlocal current_id, current_title, current_tags, current_text
        if not current_id:
            return
        text = "\n".join(current_text)
        index[current_id] = {
            "title": current_title or "Untitled",
            "tags": current_tags,
            "text": text,
            "keywords": extract_keywords(" ".join([current_title, current_tags, text])),
        }
        current_id = None
        current_title = ""
        current_tags = ""
        current_text = []

    for path in sorted(file_paths):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        for line in lines:
            stripped = line.strip()
            if stripped.startswith(".. guideline::"):
                flush_current()
                current_title = stripped[len(".. guideline::") :].strip() or "Untitled"
                current_id = None
                current_tags = ""
                current_text = []
                continue
            if current_id is None:
                if stripped.startswith(":id:"):
                    current_id = stripped[len(":id:") :].strip() or "unknown"
                elif stripped.startswith(":tags:"):
                    current_tags = stripped[len(":tags:") :].strip()
                elif stripped:
                    current_text.append(stripped)
                continue

            if stripped.startswith(":tags:"):
                current_tags = stripped[len(":tags:") :].strip()
                continue

            if stripped:
                current_text.append(stripped)

        flush_current()

    return index


def score_guideline_relevance(
    paragraph_text: str,
    section_id: str,
    guideline_index: dict[str, dict[str, Any]],
    section_index: dict[str, list[dict[str, str]]],
    chapter_index: dict[str, list[dict[str, str]]],
) -> tuple[int, list[dict[str, Any]]]:
    paragraph_keywords = extract_keywords(paragraph_text)
    normative = contains_normative_language(paragraph_text)
    section_key, chapter_key = parse_section_id(section_id)
    same_section = section_index.get(section_key or "", []) if section_key else []
    same_chapter = chapter_index.get(chapter_key or "", []) if chapter_key else []

    base_score = 0
    if same_section:
        base_score += 40
    elif same_chapter:
        base_score += 25

    matches: list[dict[str, Any]] = []
    for guideline_id, info in guideline_index.items():
        overlap = paragraph_keywords & info["keywords"]
        overlap_score = min(35, 5 * len(overlap))
        score = base_score + overlap_score + (15 if normative else 0)
        matches.append(
            {
                "guideline_id": guideline_id,
                "title": info["title"],
                "score": min(100, score),
                "overlap": sorted(overlap)[:10],
                "same_section": any(g["id"] == guideline_id for g in same_section),
                "same_chapter": any(g["id"] == guideline_id for g in same_chapter),
                "normative": normative,
            }
        )

    matches.sort(key=lambda item: item["score"], reverse=True)
    top_matches = matches[:3]
    overall_score = top_matches[0]["score"] if top_matches else base_score
    return overall_score, top_matches


def build_guideline_index(
    fls_to_guidelines: dict[str, list[dict[str, str]]],
    locked_paragraphs: dict[str, dict[str, str]],
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]]:
    section_index: dict[str, list[dict[str, str]]] = {}
    chapter_index: dict[str, list[dict[str, str]]] = {}
    for fls_id, guidelines in fls_to_guidelines.items():
        section_id = locked_paragraphs.get(fls_id, {}).get("section_id", "")
        section_key, chapter_key = parse_section_id(section_id)
        if not section_key or not chapter_key:
            continue
        section_index.setdefault(section_key, []).extend(guidelines)
        chapter_index.setdefault(chapter_key, []).extend(guidelines)
    return section_index, chapter_index


def dedupe_guidelines(guidelines: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for guideline in guidelines:
        gid = guideline.get("id") or "unknown"
        if gid in seen:
            continue
        seen.add(gid)
        result.append(guideline)
    return result


def assess_new_paragraphs(
    added_entries: list[dict[str, Any]],
    section_index: dict[str, list[dict[str, str]]],
    chapter_index: dict[str, list[dict[str, str]]],
) -> list[dict[str, Any]]:
    assessments: list[dict[str, Any]] = []
    for entry in added_entries:
        fls_id = entry["fls_id"]
        section_id = entry["live"].get("section_id", "")
        section_key, chapter_key = parse_section_id(section_id)
        same_section = (
            dedupe_guidelines(section_index.get(section_key, [])) if section_key else []
        )
        same_chapter = (
            dedupe_guidelines(chapter_index.get(chapter_key, [])) if chapter_key else []
        )
        assessments.append(
            {
                "fls_id": fls_id,
                "section_id": section_id,
                "link": entry["live"].get("link", ""),
                "same_section_guidelines": same_section,
                "same_chapter_guidelines": [
                    guideline
                    for guideline in same_chapter
                    if guideline not in same_section
                ],
            }
        )
    return assessments


def detect_header_changes(
    baseline_sections: dict[str, fls_rst.SectionData],
    current_sections: dict[str, fls_rst.SectionData],
) -> list[dict[str, Any]]:
    header_changes: list[dict[str, Any]] = []
    for section_id, baseline in baseline_sections.items():
        current = current_sections.get(section_id)
        if not current:
            continue
        if (
            baseline.title != current.title
            or baseline.document_title != current.document_title
        ):
            header_changes.append(
                {
                    "section_id": section_id,
                    "document_title_before": baseline.document_title,
                    "document_title_after": current.document_title,
                    "section_title_before": baseline.title,
                    "section_title_after": current.title,
                    "section_path_before": baseline.path,
                    "section_path_after": current.path,
                }
            )
    return header_changes


def detect_section_reorders(
    baseline_sections: dict[str, fls_rst.SectionData],
    current_sections: dict[str, fls_rst.SectionData],
) -> list[dict[str, Any]]:
    reorders: list[dict[str, Any]] = []
    for section_id, baseline in baseline_sections.items():
        current = current_sections.get(section_id)
        if not current:
            continue
        if baseline.path != current.path:
            reorders.append(
                {
                    "section_id": section_id,
                    "title": current.title,
                    "path_before": baseline.path,
                    "path_after": current.path,
                    "document": current.document,
                }
            )
    return reorders


def summarize_counts(
    diff: dict[str, list[dict[str, Any]]],
    header_changes: list[dict[str, Any]],
    section_reorders: list[dict[str, Any]],
) -> dict[str, int]:
    added = len(diff.get("added", []))
    removed = len(diff.get("removed", []))
    content_changed = sum(
        1 for entry in diff.get("changed", []) if entry.get("content_changed")
    )
    section_changed = sum(
        1 for entry in diff.get("changed", []) if entry.get("section_changed")
    )
    renumbered_only = sum(
        1
        for entry in diff.get("changed", [])
        if entry.get("section_changed") and not entry.get("content_changed")
    )
    return {
        "added": added,
        "removed": removed,
        "content_changed": content_changed,
        "section_changed": section_changed,
        "renumbered_only": renumbered_only,
        "header_changed": len(header_changes),
        "section_reordered": len(section_reorders),
    }


def load_text_snapshot(path: Path) -> dict[str, str]:
    data = load_json_file(path)
    texts = data.get("texts", {})
    if isinstance(texts, dict):
        return {str(key): str(value) for key, value in texts.items()}
    return {}


def write_text_snapshot(path: Path, texts: dict[str, str], source: str, commit: str) -> None:
    snapshot = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fls_source": source,
            "fls_commit": commit,
        },
        "texts": texts,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")


def build_text_diffs(
    entries: list[dict[str, Any]],
    before_texts: dict[str, str],
    after_texts: dict[str, str],
    delta_path: Path | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    diffs: list[dict[str, Any]] = []
    warnings: list[str] = []
    for entry in entries:
        fls_id = entry["fls_id"]
        before = before_texts.get(fls_id, "")
        after = after_texts.get(fls_id, "")
        diff_lines = list(
            difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile="before",
                tofile="after",
                lineterm="",
            )
        )
        ansi_diff = None
        if delta_path:
            rendered, error = delta_diff.render_delta_diff(delta_path, diff_lines)
            if error:
                warnings.append(f"{fls_id}: {error}")
            if rendered is not None:
                ansi_diff = rendered.splitlines()
        note = None
        if before and after and before == after:
            note = "No visible text change (checksum changed)."
        diffs.append(
            {
                "fls_id": fls_id,
                "section_id": entry["live"].get("section_id", ""),
                "link": entry["live"].get("link", ""),
                "before_text": before,
                "after_text": after,
                "diff": diff_lines,
                "ansi_diff": ansi_diff,
                "note": note,
            }
        )
    return diffs, warnings


def build_markdown_report(
    diff: dict[str, list[dict[str, Any]]],
    affected_guidelines: dict[str, dict[str, Any]],
    guideline_files: dict[str, str],
    detailed_lines: list[str],
    counts: dict[str, int],
    header_changes: list[dict[str, Any]],
    section_reorders: list[dict[str, Any]],
    new_paragraph_assessments: list[dict[str, Any]],
    content_diffs: list[dict[str, Any]],
    added_texts: dict[str, str],
    removed_texts: dict[str, str],
    spec_lock_path: Path,
    live_source: str,
    baseline_commit: str | None,
    current_commit: str | None,
    include_legacy: bool,
    relevance_entries: list[dict[str, Any]],
    include_heuristic_details: bool,
    diff_field: str = "diff",
    fallback_diff_field: str | None = None,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    lines: list[str] = []

    lines.append("# FLS Spec Lock Audit Report")
    lines.append("")

    lines.append(f"- Generated: {generated_at}")
    lines.append(f"- Spec lock: `{spec_lock_path}`")
    lines.append(f"- FLS source: `{live_source}`")
    if baseline_commit:
        lines.append(f"- Baseline commit: `{baseline_commit}`")
    if current_commit:
        lines.append(f"- Current commit: `{current_commit}`")
    lines.append("")

    lines.append("## Summary")
    lines.append(f"- Added IDs: {counts['added']}")
    lines.append(f"- Removed IDs: {counts['removed']}")
    lines.append(f"- Content changed: {counts['content_changed']}")
    lines.append(f"- Renumbered only: {counts['renumbered_only']}")
    lines.append(f"- Header changes: {counts['header_changed']}")
    lines.append(f"- Section reorders: {counts['section_reordered']}")
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

    lines.append("## Potentially Relevant Guidelines (Heuristic)")
    if not relevance_entries:
        lines.append("- None")
    else:
        if not include_heuristic_details:
            lines.append("Note: use `--include-heuristic-details` to show matches.")
        for entry in sorted(
            relevance_entries, key=lambda item: item["score"], reverse=True
        ):
            lines.append(
                f"- {entry['fls_id']} ({entry['section_id']}) score {entry['score']} [{entry['kind']}]"
            )
            if include_heuristic_details:
                if not entry["matches"]:
                    lines.append("  - No guideline matches")
                    continue
                for match in entry["matches"]:
                    reason_parts = []
                    if match["same_section"]:
                        reason_parts.append("same section")
                    elif match["same_chapter"]:
                        reason_parts.append("same chapter")
                    if match["normative"]:
                        reason_parts.append("normative language")
                    if match["overlap"]:
                        reason_parts.append(
                            f"overlap: {', '.join(match['overlap'])}"
                        )
                    reason = "; ".join(reason_parts) if reason_parts else "no signals"
                    lines.append(
                        f"  - {match['guideline_id']}: {match['title']} (score {match['score']}; {reason})"
                    )
    lines.append("")

    lines.append("## New Paragraphs With Nearby Guidelines")
    if not new_paragraph_assessments:
        lines.append("- None")
    else:
        for entry in new_paragraph_assessments:
            same_section = entry["same_section_guidelines"]
            same_chapter = entry["same_chapter_guidelines"]
            if not same_section and not same_chapter:
                continue
            lines.append(f"- {entry['fls_id']} ({entry['section_id']})")
            if same_section:
                gids = ", ".join(g["id"] for g in same_section)
                lines.append(f"  - Same section: {gids}")
            if same_chapter:
                gids = ", ".join(g["id"] for g in same_chapter)
                lines.append(f"  - Same chapter: {gids}")
    lines.append("")

    lines.append("## Added Paragraphs")
    if not diff.get("added"):
        lines.append("- None")
    else:
        for entry in diff.get("added", []):
            fls_id = entry["fls_id"]
            section_id = entry["live"].get("section_id", "")
            link = entry["live"].get("link", "")
            lines.append(f"- {fls_id} ({section_id}) {link}")
            text = added_texts.get(fls_id)
            if text:
                lines.append("  ```text")
                lines.append(text)
                lines.append("  ```")
    lines.append("")

    lines.append("## Removed Paragraphs")
    if not diff.get("removed"):
        lines.append("- None")
    else:
        for entry in diff.get("removed", []):
            fls_id = entry["fls_id"]
            section_id = entry["locked"].get("section_id", "")
            link = entry["locked"].get("link", "")
            lines.append(f"- {fls_id} ({section_id}) {link}")
            text = removed_texts.get(fls_id)
            if text:
                lines.append("  ```text")
                lines.append(text)
                lines.append("  ```")
    lines.append("")

    lines.append("## Content Changes")
    if not content_diffs:
        lines.append("- None")
    else:
        for entry in content_diffs:
            lines.append(
                f"- {entry['fls_id']} ({entry['section_id']}) {entry['link']}"
            )
            if entry["note"]:
                lines.append(f"  Note: {entry['note']}")
            if entry["before_text"]:
                lines.append("  Before:")
                lines.append("  ```text")
                lines.append(entry["before_text"])
                lines.append("  ```")
            else:
                lines.append("  Before: (no baseline text)")
            if entry["after_text"]:
                lines.append("  After:")
                lines.append("  ```text")
                lines.append(entry["after_text"])
                lines.append("  ```")
            else:
                lines.append("  After: (no current text)")
            diff_lines = entry.get(diff_field) or []
            if not diff_lines and fallback_diff_field:
                diff_lines = entry.get(fallback_diff_field) or []
            if diff_lines:
                lines.append("  Diff:")
                lines.append("  ```diff")
                lines.extend(diff_lines)
                lines.append("  ```")
    lines.append("")

    lines.append("## Renumbered Only")
    renumbered_only = [
        entry
        for entry in diff.get("changed", [])
        if entry.get("section_changed") and not entry.get("content_changed")
    ]
    if not renumbered_only:
        lines.append("- None")
    else:
        for entry in renumbered_only:
            fls_id = entry["fls_id"]
            before = entry["locked"].get("section_id", "")
            after = entry["live"].get("section_id", "")
            lines.append(f"- {fls_id}: {before} -> {after}")
    lines.append("")

    lines.append("## Section Reordering")
    if not section_reorders:
        lines.append("- None")
    else:
        for entry in section_reorders:
            lines.append(
                f"- {entry['section_id']} ({entry['document']}): {entry['path_before']} -> {entry['path_after']}"
            )
    lines.append("")

    lines.append("## Header Changes")
    if not header_changes:
        lines.append("- None")
    else:
        for entry in header_changes:
            lines.append(f"- {entry['section_id']}")
            if entry["document_title_before"] != entry["document_title_after"]:
                lines.append(
                    f"  - Document: {entry['document_title_before']} -> {entry['document_title_after']}"
                )
            if entry["section_title_before"] != entry["section_title_after"]:
                lines.append(
                    f"  - Section: {entry['section_title_before']} -> {entry['section_title_after']}"
                )
    lines.append("")

    if include_legacy:
        lines.append("## Detailed Differences (Legacy Format)")
        lines.append("```text")
        lines.extend(detailed_lines or ["No differences detected."])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    args = parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    spec_lock_path = repo_root / "src" / "spec.lock"
    session = requests.Session()

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
            live_data = fetch_json(DEFAULT_FLS_URL, session)
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

    spec_metadata = load_spec_lock_metadata(spec_lock_path)
    baseline_commit = args.baseline_fls_commit or spec_metadata.get(
        "fls_deployed_commit"
    )
    current_commit = args.current_fls_commit

    needs_current_commit = not args.summary_only
    needs_baseline_commit = not args.summary_only and not args.baseline_text_snapshot

    if needs_current_commit and not current_commit:
        try:
            current_commit = resolve_deployment_commit(
                session, args.current_deployment_offset
            )
        except Exception as exc:
            print(f"Current commit not available: {exc}", file=sys.stderr)
            return 1

    if needs_baseline_commit and not baseline_commit:
        try:
            baseline_commit = resolve_deployment_commit(
                session, args.baseline_deployment_offset
            )
        except Exception as exc:
            print(f"Baseline commit not available: {exc}", file=sys.stderr)
            return 1

    header_changes: list[dict[str, Any]] = []
    section_reorders: list[dict[str, Any]] = []
    baseline_texts: dict[str, str] = {}
    current_texts: dict[str, str] = {}
    guideline_index = build_guideline_text_index(repo_root)
    delta_path: Path | None = None
    baseline_worktree: Path | None = None
    current_worktree: Path | None = None
    baseline_sections: dict[str, fls_rst.SectionData] = {}
    current_sections: dict[str, fls_rst.SectionData] = {}
    parse_paths_baseline: set[Path] | None = None
    parse_paths_current: set[Path] | None = None

    if not args.summary_only:
        cache_dir = resolve_cache_dir(repo_root, args.fls_repo_cache_dir)
        try:
            delta_path, delta_warning = delta_diff.resolve_delta_binary(
                cache_dir,
                session,
                args.delta_path,
                args.no_delta,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        if delta_warning:
            print(f"Delta: {delta_warning}", file=sys.stderr)
        if baseline_commit and not args.baseline_text_snapshot:
            try:
                baseline_worktree = fls_repo.ensure_worktree(
                    cache_dir, baseline_commit
                )
            except Exception as exc:
                print(f"Failed to prepare baseline FLS repo: {exc}", file=sys.stderr)
                return 1

        if current_commit:
            try:
                current_worktree = fls_repo.ensure_worktree(cache_dir, current_commit)
            except Exception as exc:
                print(f"Failed to prepare current FLS repo: {exc}", file=sys.stderr)
                return 1

        diff_has_texts = bool(
            diff.get("added")
            or diff.get("removed")
            or any(
                entry.get("content_changed") for entry in diff.get("changed", [])
            )
        )
        if (
            baseline_worktree
            and current_worktree
            and baseline_commit
            and current_commit
        ):
            try:
                repo_dir = fls_repo.ensure_repo(cache_dir)
                parse_paths_baseline, parse_paths_current = resolve_parse_paths(
                    repo_dir,
                    baseline_worktree,
                    current_worktree,
                    baseline_commit,
                    current_commit,
                )
            except Exception as exc:
                print(
                    f"Failed to compute changed files for selective parsing: {exc}",
                    file=sys.stderr,
                )
                parse_paths_baseline = None
                parse_paths_current = None

        if diff_has_texts and parse_paths_current is not None and not parse_paths_current:
            parse_paths_baseline = None
            parse_paths_current = None

        if baseline_worktree and not args.baseline_text_snapshot:
            try:
                baseline_paragraphs, baseline_sections = fls_rst.parse_spec(
                    baseline_worktree / "src",
                    parse_paths_baseline,
                )
            except Exception as exc:
                print(f"Failed to parse baseline FLS spec: {exc}", file=sys.stderr)
                return 1
            baseline_texts = {
                fls_id: data.text for fls_id, data in baseline_paragraphs.items()
            }

        if current_worktree:
            try:
                current_paragraphs, current_sections = fls_rst.parse_spec(
                    current_worktree / "src",
                    parse_paths_current,
                )
            except Exception as exc:
                print(f"Failed to parse current FLS spec: {exc}", file=sys.stderr)
                return 1
            current_texts = {
                fls_id: data.text for fls_id, data in current_paragraphs.items()
            }

        header_changes = detect_header_changes(baseline_sections, current_sections)
        section_reorders = detect_section_reorders(
            baseline_sections, current_sections
        )

        if args.baseline_text_snapshot:
            baseline_path = resolve_snapshot_path(repo_root, args.baseline_text_snapshot)
            try:
                baseline_texts = load_text_snapshot(baseline_path)
            except RuntimeError as exc:
                print(str(exc), file=sys.stderr)
                return 1

        if args.write_text_snapshot:
            snapshot_path = resolve_snapshot_output(
                repo_root,
                args.write_text_snapshot,
            )
            write_text_snapshot(
                snapshot_path,
                current_texts,
                live_source,
                current_commit or "",
            )
            print(f"Wrote text snapshot: {snapshot_path}")

    counts = summarize_counts(diff, header_changes, section_reorders)

    if args.summary_only:
        print("FLS spec lock audit summary")
        print(f"Added IDs: {counts['added']}")
        print(f"Removed IDs: {counts['removed']}")
        print(f"Content changed: {counts['content_changed']}")
        print(f"Renumbered only: {counts['renumbered_only']}")
        print(f"Header changes: {counts['header_changed']}")
        print(f"Section reorders: {counts['section_reordered']}")
        print(f"Guidelines affected: {len(affected_guidelines)}")
        if affected_guidelines:
            for guideline_id, info in sorted(affected_guidelines.items()):
                fls_ids = sorted({change["fls_id"] for change in info["changes"]})
                print(f"{guideline_id}: {', '.join(fls_ids)}")
        if args.fail_on_impact and affected_guidelines:
            return 2
        return 0

    section_index, chapter_index = build_guideline_index(
        fls_to_guidelines, locked_paragraphs
    )
    new_paragraph_assessments = assess_new_paragraphs(
        diff.get("added", []), section_index, chapter_index
    )

    content_changed_entries = [
        entry for entry in diff.get("changed", []) if entry.get("content_changed")
    ]
    added_ids = [entry["fls_id"] for entry in diff.get("added", [])]
    removed_ids = [entry["fls_id"] for entry in diff.get("removed", [])]

    removed_texts = {
        fls_id: baseline_texts.get(fls_id, "") for fls_id in removed_ids
    }
    added_texts = {fls_id: current_texts.get(fls_id, "") for fls_id in added_ids}
    content_diffs, delta_warnings = build_text_diffs(
        content_changed_entries,
        baseline_texts,
        current_texts,
        delta_path,
    )
    if delta_warnings:
        for warning in delta_warnings:
            print(f"Delta: {warning}", file=sys.stderr)
    if args.print_diffs:
        if not content_diffs:
            print("No content diffs to print.")
        else:
            if delta_path is None and not args.no_delta:
                print("Delta not available; printing unified diffs.", file=sys.stderr)
            for entry in content_diffs:
                header = f"{entry['fls_id']} ({entry['section_id']}) {entry['link']}"
                print(f"Diff for {header}".rstrip())
                diff_lines = entry.get("ansi_diff") or entry.get("diff") or []
                if diff_lines:
                    sys.stdout.write("\n".join(diff_lines) + "\n")
                else:
                    print("(no diff)")
                print("")

    relevance_entries: list[dict[str, Any]] = []
    for entry in diff.get("added", []):
        fls_id = entry["fls_id"]
        text = current_texts.get(fls_id, "")
        section_id = entry["live"].get("section_id", "")
        score, matches = score_guideline_relevance(
            text,
            section_id,
            guideline_index,
            section_index,
            chapter_index,
        )
        relevance_entries.append(
            {
                "fls_id": fls_id,
                "section_id": section_id,
                "link": entry["live"].get("link", ""),
                "score": score,
                "matches": matches,
                "kind": "added",
            }
        )

    for entry in content_changed_entries:
        fls_id = entry["fls_id"]
        text = current_texts.get(fls_id, "")
        section_id = entry["live"].get("section_id", "")
        score, matches = score_guideline_relevance(
            text,
            section_id,
            guideline_index,
            section_index,
            chapter_index,
        )
        relevance_entries.append(
            {
                "fls_id": fls_id,
                "section_id": section_id,
                "link": entry["live"].get("link", ""),
                "score": score,
                "matches": matches,
                "kind": "content_changed",
            }
        )

    output_dir = resolve_output_dir(repo_root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.include_heuristic_details:
        relevance_report = relevance_entries
    else:
        relevance_report = [
            {**{k: v for k, v in entry.items() if k != "matches"}, "matches": []}
            for entry in relevance_entries
        ]

    json_content_diffs = [
        {k: v for k, v in entry.items() if k != "ansi_diff"}
        for entry in content_diffs
    ]

    report = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spec_lock": str(spec_lock_path),
            "fls_source": live_source,
            "baseline_commit": baseline_commit,
            "current_commit": current_commit,
        },
        "summary": {
            "added": counts["added"],
            "removed": counts["removed"],
            "content_changed": counts["content_changed"],
            "section_changed": counts["section_changed"],
            "renumbered_only": counts["renumbered_only"],
            "header_changed": counts["header_changed"],
            "section_reordered": counts["section_reordered"],
            "affected_guidelines": len(affected_guidelines),
        },
        "changes": diff,
        "header_changes": header_changes,
        "section_reorders": section_reorders,
        "new_paragraph_assessments": new_paragraph_assessments,
        "affected_guidelines": affected_guidelines,
        "text": {
            "added": added_texts,
            "removed": removed_texts,
            "content_diffs": json_content_diffs,
        },
        "relevance": relevance_report,
    }
    if args.include_legacy_report:
        report["detailed_lines"] = detailed_lines

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
        header_changes,
        section_reorders,
        new_paragraph_assessments,
        content_diffs,
        added_texts,
        removed_texts,
        spec_lock_path,
        live_source,
        baseline_commit,
        current_commit,
        args.include_legacy_report,
        relevance_entries,
        args.include_heuristic_details,
    )
    markdown_path = output_dir / "report.md"
    markdown_path.write_text(markdown_report, encoding="utf-8")

    ansi_report = build_markdown_report(
        diff,
        affected_guidelines,
        guideline_files,
        detailed_lines,
        counts,
        header_changes,
        section_reorders,
        new_paragraph_assessments,
        content_diffs,
        added_texts,
        removed_texts,
        spec_lock_path,
        live_source,
        baseline_commit,
        current_commit,
        args.include_legacy_report,
        relevance_entries,
        args.include_heuristic_details,
        diff_field="ansi_diff",
        fallback_diff_field="diff",
    )
    ansi_path = output_dir / "report.ansi.md"
    ansi_path.write_text(ansi_report, encoding="utf-8")

    print(f"Wrote report: {markdown_path}")
    print(f"Wrote report: {ansi_path}")
    print(f"Wrote report: {report_path}")

    if args.fail_on_impact and affected_guidelines:
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
