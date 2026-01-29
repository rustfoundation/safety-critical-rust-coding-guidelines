#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
This script transforms a GitHub issue JSON into RST format for coding guidelines.

It reads a GitHub issue's JSON data from standard input, parses its body 
(which is expected to follow a specific issue template), and converts it 
into a formatted reStructuredText (.rst) guideline.

Usage:
    cat issue.json | uv run python scripts/auto-pr-helper.py
    cat issue.json | uv run python scripts/auto-pr-helper.py --save
"""

import argparse
import json
import sys

from scripts.guideline_utils import (
    extract_form_fields,
    guideline_template,
    normalize_list_separation,
    normalize_md,
    save_guideline_file,
)

if __name__ == "__main__":
    # parse arguments
    parser = argparse.ArgumentParser(
        description="Generate guideline from GitHub issue JSON."
    )
    parser.add_argument(
        "--save", action="store_true", help="Save the generated guideline file."
    )
    args = parser.parse_args()

    ## locally test with `cat scripts/test_issue_sample.json | python3 scripts/auto-pr-helper.py`
    ## or use `curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/135 | uv run python scripts/auto-pr-helper.py`

    # Read json from stdin
    stdin_issue_json = sys.stdin.read()
    json_issue = json.loads(stdin_issue_json)

    issue_number = json_issue["number"]
    issue_title = json_issue["title"]

    issue_body = json_issue["body"]
    issue_body = normalize_md(issue_body)
    issue_body = normalize_list_separation(issue_body)

    fields = extract_form_fields(issue_body)
    chapter = fields["chapter"]
    content = guideline_template(fields)

    print("=====CONTENT=====")
    print(content)
    print("=====CONTENT=END=====")

    if args.save:
        save_guideline_file(content, chapter)
