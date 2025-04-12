#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

# Convenience script to build Sphinx books, including setting up a Python
# virtual environment to install Sphinx into (removing the need to manage
# dependencies globally). Each book should have a `make.py` script that updates
# the submodules, import this shared module, and calls the main function here.

from pathlib import Path
import argparse
import subprocess
import sys
import requests
import json

# Automatically watch the following extra directories when --serve is used.
EXTRA_WATCH_DIRS = ["exts", "themes"]

SPEC_CHECKSUM_URL = "https://spec.ferrocene.dev/paragraph-ids.json"
SPEC_LOCKFILE = "spec.lock"

def build_docs(root, builder, clear, serve, debug, spec_lock_consistency_check):
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
    # Only add the --define argument if there are options to define
    if conf_opt_values:
        args.append("--define")
        for opt in conf_opt_values:
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

    return dest / builder

def update_spec_lockfile(spec_checksum_location, lockfile_location):

    try:
        response = requests.get(spec_checksum_location, stream=True)

        response.raise_for_status()

        with open(lockfile_location, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        with open(lockfile_location, 'r') as file:
            data = json.load(file)

        print("-- read in --")

        with open(lockfile_location, 'w') as outfile:
            json.dump(data, outfile, indent=4, sort_keys=True)

        print("-- wrote back out --")

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
    group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        "--ignore-spec-lock-diff",
        help="ignore fls.lock file differences with live release -- for WIP branches only",
        default=False,
        action="store_true"
    )
    parser.add_argument(
        "--update-spec-lock-file",
        help="update fls.lock file",
        action="store_true"
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
        "--debug",
        help="Debug mode for the extensions, showing exceptions",
        action="store_true",
    )
    args = parser.parse_args()

    if args.update_spec_lock_file:
        update_spec_lockfile(SPEC_CHECKSUM_URL, root / "src" / SPEC_LOCKFILE)

    rendered = build_docs(
        root, "xml" if args.xml else "html", args.clear, args.serve, args.debug, not args.ignore_spec_lock_diff
    )

