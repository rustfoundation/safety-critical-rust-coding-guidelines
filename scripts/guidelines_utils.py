# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Shared utilities for parsing GitHub issues and generating RST guideline content.

This module contains common functions used by:
- auto-pr-helper.py (for automated PR generation)
- generate-rst-comment.py (for generating preview comments)

Location: scripts/guideline_utils.py
"""

import os
import re
import sys
from textwrap import dedent, indent

import pypandoc

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(parent_dir)

from generate_guideline_templates import (
    guideline_rst_template,
    issue_header_map,
)


def md_to_rst(markdown: str) -> str:
    """Convert Markdown text to reStructuredText using Pandoc."""
    return pypandoc.convert_text(
        markdown,
        'rst',
        format='markdown',
        extra_args=['--wrap=none']
    )


def normalize_list_separation(text: str) -> str:
    """
    Ensures every new list block is preceded by a blank line,
    required for robust parsing by Pandoc when targeting RST
    """
    # Regex to identify any line that starts a Markdown list item (* or -)
    _list_item_re = re.compile(r"^[ \t]*[*-][ \t]+")

    output_buffer = []
    for line in text.splitlines():
        is_item = bool(_list_item_re.match(line))

        # Get the last line appended to the output buffer
        prev = output_buffer[-1] if output_buffer else ""

        # Check if a blank line needs to be inserted before list
        # (Current is item) AND (Prev is not blank) AND (Prev is not an item)
        if is_item and prev.strip() and not _list_item_re.match(prev):
            # Insert a blank line to clearly separate the new list block
            output_buffer.append("")

        output_buffer.append(line)

    return "\n".join(output_buffer)


def normalize_md(issue_body: str) -> str:
    """
    Fix links and mixed bold/code that confuse Markdown parser
    """
    # Fix links with inline-code: [`link`](url) => [link](url)
    issue_body = re.sub(
        r"\[\s*`([^`]+)`\s*\]\(([^)]+)\)",
        r"[\1](\2)",
        issue_body
    )

    # Fix mixed bold/code formatting
    # **`code`** => `code`
    issue_body = re.sub(
        r"\*\*`([^`]+)`\*\*",
        r"`\1`",
        issue_body
    )

    # `**code**` => `code`
    issue_body = re.sub(
        r"`\*\*([^`]+)\*\*`",
        r"`\1`",
        issue_body
    )

    return issue_body


def extract_form_fields(issue_body: str) -> dict:
    """
    Parse issue body (from GitHub issue template) into a dict of field values.
    
    Args:
        issue_body: The raw body text from a GitHub issue
        
    Returns:
        Dictionary with field names as keys and their values
    """
    fields = dict.fromkeys(issue_header_map.values(), "")

    lines = issue_body.splitlines()
    current_key = None
    current_value_lines = []

    lines.append("### END")  # Sentinel to process last field

    # Look for '###' in every line, ### represent a sections/field in a guideline
    for line in lines:
        header_match = re.match(r"^### (.+)$", line.strip())
        if header_match:
            # Save previous field value if any
            if current_key is not None:
                value = "\n".join(current_value_lines).strip()
                # `_No response_` represents an empty field
                if value == "_No response_":
                    value = ""
                if current_key in fields:
                    fields[current_key] = value

            header = header_match.group(1).strip()
            current_key = issue_header_map.get(
                header
            )  # Map to dict key or None if unknown
            current_value_lines = []
        else:
            current_value_lines.append(line)

    return fields


def format_code_block(code: str, lang: str = "rust") -> str:
    """
    Format a code block for RST output, stripping markdown fences if present.
    
    Args:
        code: The code content, possibly wrapped in markdown fences
        lang: The language for syntax highlighting (default: rust)
        
    Returns:
        Formatted code block string with proper indentation
    """
    lines = code.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        # Strip the ```rust and ``` lines
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

    # Dedent before adding indentation
    dedented_code = dedent("\n".join(lines))

    # Add required indentation
    indented_code = "\n".join(
        f"       {line}" for line in dedented_code.splitlines()
    )

    return f"\n\n{indented_code}\n"


def guideline_template(fields: dict) -> str:
    """
    Convert a dictionary of guideline fields into proper RST format.
    
    Args:
        fields: Dictionary containing all guideline fields
        
    Returns:
        Formatted RST string for the guideline
    """
    def get(key):
        return fields.get(key, "").strip()

    amplification_text = indent(md_to_rst(get("amplification")), " " * 12)
    rationale_text = indent(md_to_rst(get("rationale")), " " * 16)
    non_compliant_ex_prose_text = indent(
        md_to_rst(get("non_compliant_ex_prose")), " " * 16
    )
    compliant_example_prose_text = indent(
        md_to_rst(get("compliant_example_prose")), " " * 16
    )

    guideline_text = guideline_rst_template(
        guideline_title=get("guideline_title"),
        category=get("category"),
        status=get("status"),
        release_begin=get("release_begin"),
        release_end=get("release_end"),
        fls_id=get("fls_id"),
        decidability=get("decidability"),
        scope=get("scope"),
        tags=get("tags"),
        amplification=amplification_text,
        rationale=rationale_text,
        non_compliant_ex_prose=non_compliant_ex_prose_text,
        non_compliant_ex=format_code_block(get("non_compliant_ex")),
        compliant_example_prose=compliant_example_prose_text,
        compliant_example=format_code_block(get("compliant_example")),
    )

    return guideline_text


def chapter_to_filename(chapter: str) -> str:
    """
    Convert chapter name to filename slug.
    
    Args:
        chapter: Chapter name (e.g., "Associated Items", "Concurrency")
        
    Returns:
        Filename slug (e.g., "associated-items", "concurrency")
    """
    return chapter.lower().replace(" ", "-")


def save_guideline_file(content: str, chapter: str):
    """
    Append a guideline to a chapter file.
    
    Args:
        content: The RST content to append
        chapter: The chapter name
    """
    filename = f"src/coding-guidelines/{chapter_to_filename(chapter)}.rst"
    with open(filename, "a", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved guideline to {filename}")
