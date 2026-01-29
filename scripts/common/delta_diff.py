# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import requests

DELTA_VERSION = "0.18.2"
DELTA_RELEASE_BASE = (
    f"https://github.com/dandavison/delta/releases/download/{DELTA_VERSION}"
)

DELTA_ASSETS: dict[str, dict[str, str]] = {
    "x86_64-unknown-linux-gnu": {
        "filename": f"delta-{DELTA_VERSION}-x86_64-unknown-linux-gnu.tar.gz",
        "sha256": "99607c43238e11a77fe90a914d8c2d64961aff84b60b8186c1b5691b39955b0f",
        "binary": "delta",
    },
    "aarch64-unknown-linux-gnu": {
        "filename": f"delta-{DELTA_VERSION}-aarch64-unknown-linux-gnu.tar.gz",
        "sha256": "adf7674086daa4582f598f74ce9caa6b70c1ba8f4a57d2911499b37826b014f9",
        "binary": "delta",
    },
    "aarch64-apple-darwin": {
        "filename": f"delta-{DELTA_VERSION}-aarch64-apple-darwin.tar.gz",
        "sha256": "6ba38dce9f91ee1b9a24aa4aede1db7195258fe176c3f8276ae2d4457d8170a0",
        "binary": "delta",
    },
    "x86_64-pc-windows-msvc": {
        "filename": f"delta-{DELTA_VERSION}-x86_64-pc-windows-msvc.zip",
        "sha256": "6ea59864091b4cfca89d9ee38388ff1a3ccdc8244b6e1cdd5201259de89b0b06",
        "binary": "delta.exe",
    },
}

DELTA_ARGS = [
    "--color-only",
    "--paging=never",
    "--side-by-side",
    "--line-numbers",
    "--file-style",
    "bold yellow ul",
    "--file-decoration-style",
    "none",
    "--hunk-header-decoration-style",
    "none",
    "--max-line-length",
    "0",
    "--wrap-max-lines",
    "0",
    "--whitespace-error-style",
    "red reverse",
]


def detect_target() -> str | None:
    system = sys.platform
    machine = platform.machine().lower()
    if system.startswith("linux"):
        if machine in ("x86_64", "amd64"):
            return "x86_64-unknown-linux-gnu"
        if machine in ("aarch64", "arm64"):
            return "aarch64-unknown-linux-gnu"
    if system == "darwin":
        if machine in ("aarch64", "arm64"):
            return "aarch64-apple-darwin"
    if system == "win32":
        if machine in ("x86_64", "amd64"):
            return "x86_64-pc-windows-msvc"
    return None


def resolve_delta_binary(
    cache_dir: Path,
    session: requests.Session,
    delta_path: Path | None,
    disable_delta: bool,
) -> tuple[Path | None, str | None]:
    if disable_delta:
        return None, None

    if delta_path:
        resolved = delta_path
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        if not resolved.exists():
            raise RuntimeError(f"delta binary not found at {resolved}")
        if not resolved.is_file():
            raise RuntimeError(f"delta path is not a file: {resolved}")
        return resolved, None

    warning = None
    target = detect_target()
    if target:
        try:
            return install_delta(cache_dir, session, target), None
        except RuntimeError as exc:
            warning = str(exc)
    else:
        warning = f"delta not available for platform {sys.platform} {platform.machine()}"

    system_delta = shutil.which("delta")
    if system_delta:
        return Path(system_delta), warning

    return None, warning


def install_delta(cache_dir: Path, session: requests.Session, target: str) -> Path:
    info = DELTA_ASSETS.get(target)
    if not info:
        raise RuntimeError(f"delta target {target} is not supported")

    install_dir = cache_dir / "tools" / "delta" / DELTA_VERSION / target
    binary_path = install_dir / info["binary"]
    if binary_path.exists():
        return binary_path

    install_dir.mkdir(parents=True, exist_ok=True)
    archive_path = install_dir / info["filename"]
    if archive_path.exists() and not verify_sha256(archive_path, info["sha256"]):
        archive_path.unlink()

    if not archive_path.exists():
        url = f"{DELTA_RELEASE_BASE}/{info['filename']}"
        download_asset(session, url, archive_path)

    if not verify_sha256(archive_path, info["sha256"]):
        raise RuntimeError(f"delta checksum mismatch for {archive_path.name}")

    with tempfile.TemporaryDirectory(dir=install_dir) as temp_dir:
        temp_path = Path(temp_dir)
        extract_archive(archive_path, temp_path)
        extracted = find_binary(temp_path, info["binary"])
        shutil.copy2(extracted, binary_path)

    if os.name != "nt":
        binary_path.chmod(binary_path.stat().st_mode | 0o111)

    return binary_path


def download_asset(session: requests.Session, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as temp_file:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    temp_file.write(chunk)
            temp_path = Path(temp_file.name)
    temp_path.replace(dest)


def verify_sha256(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def extract_archive(archive_path: Path, dest_dir: Path) -> None:
    if archive_path.name.endswith(".tar.gz"):
        with tarfile.open(archive_path, "r:gz") as archive:
            safe_extract_tar(archive, dest_dir)
        return
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path, "r") as archive:
            safe_extract_zip(archive, dest_dir)
        return
    raise RuntimeError(f"Unsupported delta archive {archive_path.name}")


def safe_extract_tar(archive: tarfile.TarFile, dest_dir: Path) -> None:
    for member in archive.getmembers():
        member_path = dest_dir / member.name
        if not is_within_directory(dest_dir, member_path):
            raise RuntimeError("Blocked tar extraction outside destination")
    archive.extractall(dest_dir)


def safe_extract_zip(archive: zipfile.ZipFile, dest_dir: Path) -> None:
    for member in archive.infolist():
        member_path = dest_dir / member.filename
        if not is_within_directory(dest_dir, member_path):
            raise RuntimeError("Blocked zip extraction outside destination")
    archive.extractall(dest_dir)


def is_within_directory(directory: Path, target: Path) -> bool:
    directory_resolved = directory.resolve()
    target_resolved = target.resolve(strict=False)
    if target_resolved == directory_resolved:
        return True
    return str(target_resolved).startswith(str(directory_resolved) + os.sep)


def find_binary(root: Path, binary_name: str) -> Path:
    matches = list(root.rglob(binary_name))
    if not matches:
        raise RuntimeError(f"delta binary {binary_name} not found in archive")
    matches.sort()
    return matches[0]


def render_delta_diff(delta_path: Path, diff_lines: list[str]) -> tuple[str | None, str | None]:
    if not diff_lines:
        return None, None
    diff_text = "\n".join(diff_lines)
    if not diff_text.endswith("\n"):
        diff_text += "\n"
    result = subprocess.run(
        [str(delta_path), *DELTA_ARGS],
        input=diff_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or f"delta exited with status {result.returncode}"
        return None, error
    return result.stdout, None
