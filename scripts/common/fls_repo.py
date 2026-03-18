# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from __future__ import annotations

import subprocess
from pathlib import Path

FLS_REPO_URL = "https://github.com/rust-lang/fls.git"


def _run_git(repo_dir: Path, args: list[str]) -> None:
    subprocess.run(["git", "-C", str(repo_dir), *args], check=True)


def ensure_repo(cache_dir: Path, repo_url: str = FLS_REPO_URL) -> Path:
    repo_dir = cache_dir / "fls-repo"
    if repo_dir.exists():
        return repo_dir

    cache_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", repo_url, str(repo_dir)],
        check=True,
    )
    return repo_dir


def ensure_commit(repo_dir: Path, commit: str) -> None:
    try:
        _run_git(repo_dir, ["cat-file", "-e", f"{commit}^{{commit}}"])
    except subprocess.CalledProcessError:
        _run_git(repo_dir, ["fetch", "origin", commit])


def worktree_path(cache_dir: Path, commit: str) -> Path:
    safe_commit = commit.replace("/", "_")
    return cache_dir / "worktrees" / safe_commit


def ensure_worktree(cache_dir: Path, commit: str) -> Path:
    repo_dir = ensure_repo(cache_dir)
    ensure_commit(repo_dir, commit)

    worktree_dir = worktree_path(cache_dir, commit)
    if worktree_dir.exists():
        return worktree_dir

    worktree_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_git(repo_dir, ["worktree", "add", "--detach", str(worktree_dir), commit])
    return worktree_dir
