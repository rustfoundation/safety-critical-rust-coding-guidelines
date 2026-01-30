#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

# Convenience script to build Sphinx books, including setting up a Python
# virtual environment to install Sphinx into (removing the need to manage
# dependencies globally). Each book should have a `make.py` script that updates
# the submodules, import this shared module, and calls the main function here.

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import requests

# Automatically watch the following extra directories when --serve is used.
EXTRA_WATCH_DIRS = ["exts", "themes"]

SPEC_CHECKSUM_URL = "https://rust-lang.github.io/fls/paragraph-ids.json"
SPEC_LOCKFILE = "spec.lock"
PAGES_DEPLOYMENTS_URL = "https://api.github.com/repos/rust-lang/fls/deployments"


def build_docs(
    root: Path,
    builder: str,
    clear: bool,
    serve: bool,
    debug: bool,
    offline: bool,
    spec_lock_consistency_check: bool,
    validate_urls: bool,
) -> Path:
    """
    Builds the Sphinx documentation with the specified options.

    Args:
        root: The root directory of the documentation.
        builder: The builder to use (e.g., 'html', 'xml').
        clear: Whether to disable incremental builds.
        serve: Whether to start a local server with live reload.
        debug: Whether to enable debug mode.
        offline: Whether to build in offline mode.
        spec_lock_consistency_check: Whether to check spec lock consistency.
        validate_urls: Whether to validate bibliography URLs.

    Returns:
        Path: The path to the generated documentation.
    """

    dest = root / "build"

    args = ["-b", builder, "-d", dest / "doctrees"]

    if debug:
        # Disable parallel builds and show exceptions in debug mode.
        #
        # We can't show exceptions in parallel mode because in parallel mode
        # all exceptions will be swallowed up by Python's multiprocessing.
        # That's also why we don't show exceptions outside of debug mode.
        args += ["-j", "1", "-T"]
    else:
        # Enable parallel builds:
        args += ["-j", "auto"]
    if clear:
        args.append("-E")

    # Initialize an empty list for configuration options (without --define)
    conf_opt_values = []
    # Add configuration options as needed
    if not spec_lock_consistency_check:
        conf_opt_values.append("enable_spec_lock_consistency=0")
    if offline:
        conf_opt_values.append("offline=1")
    if debug:
        conf_opt_values.append("debug=1")
    if validate_urls:
        conf_opt_values.append("bibliography_check_urls=1")

    # Only add the --define argument if there are options to define
    if conf_opt_values:
        for opt in conf_opt_values:
            args.append("--define")  # each option needs its own --define
            args.append(opt)

    if serve:
        for extra_watch_dir in EXTRA_WATCH_DIRS:
            extra_watch_dir = root / extra_watch_dir
            if extra_watch_dir.exists():
                args += ["--watch", extra_watch_dir]
    else:
        # Error out at the *end* of the build if there are warnings:
        args += ["-W", "--keep-going"]

    try:
        # Tracking build time
        timer_start = time.perf_counter()
        subprocess.run(
            [
                "sphinx-autobuild" if serve else "sphinx-build",
                *args,
                root / "src",
                dest / builder,
            ],
            check=True,
        )
    except KeyboardInterrupt:
        exit(1)
    except subprocess.CalledProcessError:
        print("\nhint: if you see an exception, pass --debug to see the full traceback")
        exit(1)

    timer_end = time.perf_counter()
    print(f"\nBuild finished in {timer_end - timer_start:.2f} seconds.")
    return dest / builder


def github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (
        os.environ.get("GITHUB_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_API_TOKEN")
    )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_pages_deployments(limit: int = 10) -> list[dict[str, str]]:
    try:
        response = requests.get(
            PAGES_DEPLOYMENTS_URL,
            headers=github_headers(),
            params={"environment": "github-pages", "per_page": str(limit)},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fetch_deployment_status(statuses_url: str) -> dict[str, str] | None:
    if not statuses_url:
        return None
    try:
        response = requests.get(
            f"{statuses_url}?per_page=1", headers=github_headers(), timeout=30
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception:
        return None


def select_pages_deployment() -> tuple[dict[str, str] | None, dict[str, str] | None]:
    deployments = fetch_pages_deployments()
    for deployment in deployments:
        status = fetch_deployment_status(deployment.get("statuses_url", ""))
        if status and status.get("state") == "success":
            return deployment, status
    if deployments:
        return deployments[0], fetch_deployment_status(
            deployments[0].get("statuses_url", "")
        )
    return None, None


def extract_deployment_id(deployment: dict[str, str] | None) -> str:
    if not deployment:
        return ""
    deployment_id = deployment.get("id")
    if deployment_id is None:
        return ""
    return str(deployment_id)


def update_spec_lockfile(spec_checksum_location, lockfile_location):
    try:
        response = requests.get(spec_checksum_location, timeout=30)
        response.raise_for_status()
        data = response.json()

        previous_metadata = None
        if lockfile_location.exists():
            try:
                with open(lockfile_location, "r", encoding="utf-8") as file:
                    existing = json.load(file)
                previous_metadata = existing.get("metadata")
            except Exception:
                previous_metadata = None

        metadata = {"fls_source_url": spec_checksum_location}
        deployment, status = select_pages_deployment()
        if deployment:
            metadata.update(
                {
                    "fls_deployed_commit": deployment.get("sha", ""),
                    "fls_deployed_at": (
                        status.get("created_at", "") if status else ""
                    )
                    or deployment.get("created_at", ""),
                    "fls_pages_deployment_id": extract_deployment_id(deployment),
                }
            )

        if isinstance(previous_metadata, dict):
            previous = dict(previous_metadata)
            previous.pop("previous", None)
            metadata["previous"] = previous

        data["metadata"] = metadata

        with open(lockfile_location, "w", encoding="utf-8") as outfile:
            json.dump(data, outfile, indent=4, sort_keys=True)

        return True

    except Exception as e:
        print(f"Error downloading file: {e}")
        return False


def main(root):
    root = Path(root)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--clear", help="disable incremental builds", action="store_true"
    )
    parser.add_argument(
        "--offline",
        help="build in offline mode",
        action="store_true",
    )
    group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        "--ignore-spec-lock-diff",
        help="ignore spec.lock file differences with live release -- for WIP branches only",
        default=False,
        action="store_true",
    )
    parser.add_argument(
        "--update-spec-lock-file", help="update spec.lock file", action="store_true"
    )
    parser.add_argument(
        "--validate-urls",
        help="validate bibliography URLs (enables URL checking, typically used in CI)",
        action="store_true",
    )
    group.add_argument(
        "-s",
        "--serve",
        help="start a local server with live reload",
        action="store_true",
    )
    group.add_argument(
        "--check-links", help="Check whether all links are valid", action="store_true"
    )
    group.add_argument(
        "--xml", help="Generate Sphinx XML rather than HTML", action="store_true"
    )
    group.add_argument(
        "-v",
        "--verbose",
        help="Debug mode for the extensions, showing exceptions",
        action="store_true",
    )
    group.add_argument(
        "--debug",
        help="Debug mode for the extensions, showing exceptions",
        action="store_true",
    )
    args = parser.parse_args()

    debug = args.debug or args.verbose
    builder = "linkcheck" if args.check_links else "xml" if args.xml else "html"

    if args.update_spec_lock_file:
        update_spec_lockfile(SPEC_CHECKSUM_URL, root / "src" / SPEC_LOCKFILE)

    build_docs(
        root,
        builder,
        args.clear,
        args.serve,
        debug,
        args.offline,
        not args.ignore_spec_lock_diff,
        args.validate_urls,
    )
