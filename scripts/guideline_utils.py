# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Shared utilities for parsing GitHub issues and generating RST guideline content.

This module contains common functions used by:
- auto-pr-helper.py (for automated PR generation)
- generate-rst-comment.py (for generating preview comments)
"""

import os
import re
import sys
from pathlib import Path
from textwrap import dedent, indent

import pypandoc

script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(script_dir, ".."))
sys.path.append(parent_dir)

from generate_guideline_templates import (
    guideline_rst_template,
    issue_header_map,
)

# =============================================================================
# Constants for per-guideline file structure
# =============================================================================

# Header comment for individual guideline files
GUIDELINE_FILE_HEADER = """\
.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""

# Default guidelines directory
DEFAULT_GUIDELINES_DIR = Path("src/coding-guidelines")


# =============================================================================
# Markdown to RST conversion utilities
# =============================================================================

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


# =============================================================================
# Issue parsing utilities
# =============================================================================

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


# =============================================================================
# RST generation utilities
# =============================================================================

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

    # Process exceptions field - convert MD to RST and pre-indent for multi-line support
    exceptions_raw = get("exceptions")
    exceptions_text = ""
    if exceptions_raw:
        exceptions_text = indent(md_to_rst(exceptions_raw), " " * 12)

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
        exceptions=exceptions_text,
        rationale=rationale_text,
        non_compliant_ex_prose=non_compliant_ex_prose_text,
        non_compliant_ex=format_code_block(get("non_compliant_ex")),
        compliant_example_prose=compliant_example_prose_text,
        compliant_example=format_code_block(get("compliant_example")),
    )

    return guideline_text


# =============================================================================
# ID extraction utilities
# =============================================================================

def extract_guideline_id(content: str) -> str:
    """
    Extract the guideline ID from RST content.
    
    Args:
        content: RST content containing a guideline directive
        
    Returns:
        The guideline ID (e.g., "gui_abc123XYZ") or empty string if not found
    """
    match = re.search(r':id:\s*(gui_[a-zA-Z0-9]+)', content)
    return match.group(1) if match else ""


def extract_all_ids(content: str) -> dict:
    """
    Extract all IDs from RST content.
    
    Args:
        content: RST content
        
    Returns:
        Dictionary with keys 'guideline', 'rationale', 'compliant', 'non_compliant'
    """
    ids = {
        'guideline': '',
        'rationale': '',
        'compliant': '',
        'non_compliant': ''
    }
    
    # Guideline ID
    match = re.search(r':id:\s*(gui_[a-zA-Z0-9]+)', content)
    if match:
        ids['guideline'] = match.group(1)
    
    # Rationale ID
    match = re.search(r':id:\s*(rat_[a-zA-Z0-9]+)', content)
    if match:
        ids['rationale'] = match.group(1)
    
    # Compliant example ID
    match = re.search(r':id:\s*(compl_ex_[a-zA-Z0-9]+)', content)
    if match:
        ids['compliant'] = match.group(1)
    
    # Non-compliant example ID
    match = re.search(r':id:\s*(non_compl_ex_[a-zA-Z0-9]+)', content)
    if match:
        ids['non_compliant'] = match.group(1)
    
    return ids


# =============================================================================
# Chapter/directory name utilities
# =============================================================================

def chapter_to_filename(chapter: str) -> str:
    """
    Convert chapter name to filename slug.
    
    Args:
        chapter: Chapter name (e.g., "Associated Items", "Concurrency")
        
    Returns:
        Filename slug (e.g., "associated-items", "concurrency")
    """
    return chapter.lower().replace(" ", "-")


def chapter_to_dirname(chapter: str) -> str:
    """
    Convert chapter name to directory name (same as filename slug).
    
    Args:
        chapter: Chapter name (e.g., "Associated Items", "Concurrency")
        
    Returns:
        Directory name (e.g., "associated-items", "concurrency")
    """
    return chapter_to_filename(chapter)


def dirname_to_chapter(dirname: str) -> str:
    """
    Convert directory name back to chapter name.
    
    Args:
        dirname: Directory name (e.g., "associated-items")
        
    Returns:
        Chapter name (e.g., "Associated Items")
    """
    return dirname.replace("-", " ").title()


# =============================================================================
# Index management for per-guideline structure
# =============================================================================

def add_include_to_chapter_index(
    chapter_dir: Path,
    guideline_filename: str,
) -> bool:
    """
    Add an include directive to a chapter's index.rst, maintaining alphabetical order.
    
    Args:
        chapter_dir: Path to the chapter directory
        guideline_filename: Filename of the guideline (e.g., "gui_abc123.rst.inc")
        
    Returns:
        True if successful, False otherwise
    """
    index_path = chapter_dir / "index.rst"
    
    if not index_path.exists():
        print(f"Warning: Index file not found: {index_path}")
        return False
    
    content = index_path.read_text()
    
    # Check if already included
    if guideline_filename in content:
        print(f"Note: {guideline_filename} already in index")
        return True
    
    # Find existing include directives and their position
    include_pattern = re.compile(r'^(\s*)\.\.\ include::\s+(gui_[a-zA-Z0-9]+\.rst\.inc)\s*$', re.MULTILINE)
    matches = list(include_pattern.finditer(content))
    
    new_include = f".. include:: {guideline_filename}"
    
    if matches:
        # Get the indentation from existing includes
        indent_str = matches[0].group(1)
        new_include = f"{indent_str}.. include:: {guideline_filename}"
        
        # Find where to insert alphabetically
        existing_files = [(m.group(2), m.start(), m.end()) for m in matches]
        
        insert_pos = None
        for filename, start, end in existing_files:
            if guideline_filename < filename:
                insert_pos = start
                break
        
        if insert_pos is None:
            # Add at end (after last include)
            last_end = existing_files[-1][2]
            content = content[:last_end] + "\n" + new_include + content[last_end:]
        else:
            # Insert before the found position
            content = content[:insert_pos] + new_include + "\n" + content[insert_pos:]
    else:
        # No existing includes - add at end of file
        content = content.rstrip() + "\n\n" + new_include + "\n"
    
    index_path.write_text(content)
    return True


def remove_include_from_chapter_index(
    chapter_dir: Path,
    guideline_filename: str,
) -> bool:
    """
    Remove an include directive from a chapter's index.rst.
    
    Args:
        chapter_dir: Path to the chapter directory
        guideline_filename: Filename of the guideline to remove
        
    Returns:
        True if successful, False otherwise
    """
    index_path = chapter_dir / "index.rst"
    
    if not index_path.exists():
        return False
    
    content = index_path.read_text()
    
    # Remove the include line
    pattern = re.compile(rf'^\s*\.\.\ include::\s+{re.escape(guideline_filename)}\s*\n?', re.MULTILINE)
    new_content = pattern.sub('', content)
    
    if new_content != content:
        index_path.write_text(new_content)
        return True
    
    return False


# =============================================================================
# File operations
# =============================================================================

def save_guideline_file(
    content: str,
    chapter: str,
    guidelines_dir: Path = None,
) -> Path:
    """
    Save a guideline to a per-guideline file in the chapter directory.
    
    This creates:
    1. The chapter directory if it doesn't exist
    2. A new file named {guideline_id}.rst.inc
    3. Updates the chapter's index.rst with an include directive
    
    Args:
        content: The RST content for the guideline
        chapter: The chapter name (e.g., "Expressions")
        guidelines_dir: Base guidelines directory (default: src/coding-guidelines)
        
    Returns:
        Path to the created file
    """
    if guidelines_dir is None:
        guidelines_dir = DEFAULT_GUIDELINES_DIR
    
    chapter_slug = chapter_to_dirname(chapter)
    chapter_dir = guidelines_dir / chapter_slug
    
    # Check if per-guideline structure exists (chapter is a directory)
    if not chapter_dir.is_dir():
        # Fall back to legacy monolithic file structure
        print(f"Note: Chapter directory {chapter_dir} not found.")
        print("      Using legacy file structure. Run split_guidelines.py to migrate.")
        return save_guideline_file_legacy(content, chapter, guidelines_dir)
    
    # Extract guideline ID
    guideline_id = extract_guideline_id(content)
    if not guideline_id:
        raise ValueError("Could not extract guideline ID from content")
    
    # Create the guideline file
    guideline_filename = f"{guideline_id}.rst.inc"
    guideline_path = chapter_dir / guideline_filename
    
    # Add header and write content
    full_content = GUIDELINE_FILE_HEADER + content.strip() + "\n"
    guideline_path.write_text(full_content)
    print(f"Created guideline file: {guideline_path}")
    
    # Update the chapter index
    if add_include_to_chapter_index(chapter_dir, guideline_filename):
        print(f"Updated index: {chapter_dir / 'index.rst'}")
    
    return guideline_path


def save_guideline_file_legacy(
    content: str,
    chapter: str,
    guidelines_dir: Path = None,
) -> Path:
    """
    Append a guideline to a monolithic chapter file (legacy structure).
    
    Args:
        content: The RST content for the guideline
        chapter: The chapter name (e.g., "Expressions")
        guidelines_dir: Base guidelines directory (default: src/coding-guidelines)
        
    Returns:
        Path to the chapter file
    """
    if guidelines_dir is None:
        guidelines_dir = DEFAULT_GUIDELINES_DIR
    
    chapter_slug = chapter_to_filename(chapter)
    chapter_file = guidelines_dir / f"{chapter_slug}.rst"
    
    with open(chapter_file, "a", encoding="utf-8") as f:
        f.write(content)
    
    print(f"Appended guideline to: {chapter_file}")
    return chapter_file


def list_guidelines_in_chapter(chapter_dir: Path) -> list:
    """
    List all guideline files in a chapter directory.
    
    Args:
        chapter_dir: Path to the chapter directory
        
    Returns:
        List of guideline IDs found
    """
    guidelines = []
    
    for file_path in chapter_dir.glob("gui_*.rst.inc"):
        guideline_id = file_path.stem  # Remove .rst.inc extension
        guidelines.append(guideline_id)
    
    return sorted(guidelines)
