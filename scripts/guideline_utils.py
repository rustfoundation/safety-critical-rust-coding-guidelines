# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Shared utilities for parsing GitHub issues and generating RST guideline content.

This module contains common functions used by:
- auto-pr-helper.py (for automated PR generation)
- generate-rst-comment.py (for generating preview comments)
- split_guidelines.py (for migrating to per-guideline files)
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

# SPDX header prepended to each guideline file
GUIDELINE_FILE_HEADER = """\
.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

"""

# Default base directory for coding guidelines
DEFAULT_GUIDELINES_DIR = "src/coding-guidelines"


# =============================================================================
# Markdown to RST Conversion
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
# Issue Parsing
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
# RST Formatting
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
# Chapter/File Name Conversion
# =============================================================================

def chapter_to_filename(chapter: str) -> str:
    """
    Convert chapter name to filename slug (without extension).
    
    Args:
        chapter: Chapter name (e.g., "Associated Items", "Concurrency")
        
    Returns:
        Filename slug (e.g., "associated-items", "concurrency")
    """
    return chapter.lower().replace(" ", "-")


# Alias for consistency with new naming
chapter_to_dirname = chapter_to_filename


def dirname_to_chapter(dirname: str) -> str:
    """
    Convert directory name back to chapter display name.
    
    Args:
        dirname: Directory name (e.g., "associated-items", "ffi")
        
    Returns:
        Chapter display name (e.g., "Associated Items", "FFI")
    """
    # Special cases
    special_cases = {
        "ffi": "FFI",
    }
    if dirname in special_cases:
        return special_cases[dirname]
    
    # General case: title case
    return dirname.replace("-", " ").title()


# =============================================================================
# Guideline ID Extraction
# =============================================================================

def extract_guideline_id(rst_content: str) -> str:
    """
    Extract the guideline ID from RST content.
    
    Args:
        rst_content: The RST content containing a guideline directive
        
    Returns:
        The guideline ID (e.g., "gui_dCquvqE1csI3")
        
    Raises:
        ValueError: If no guideline ID found
    """
    match = re.search(r':id:\s*(gui_[A-Za-z0-9_]+)', rst_content)
    if match:
        return match.group(1)
    raise ValueError("Could not find guideline ID in content")


def extract_all_ids(rst_content: str) -> dict:
    """
    Extract all IDs from RST content (guideline, rationale, examples).
    
    Args:
        rst_content: The RST content
        
    Returns:
        Dict with keys: 'guideline', 'rationale', 'compliant_examples', 
        'non_compliant_examples'
    """
    result = {
        'guideline': None,
        'rationale': None,
        'compliant_examples': [],
        'non_compliant_examples': [],
    }
    
    # Guideline ID
    gui_match = re.search(r':id:\s*(gui_[A-Za-z0-9_]+)', rst_content)
    if gui_match:
        result['guideline'] = gui_match.group(1)
    
    # Rationale ID
    rat_match = re.search(r':id:\s*(rat_[A-Za-z0-9_]+)', rst_content)
    if rat_match:
        result['rationale'] = rat_match.group(1)
    
    # Compliant example IDs
    for match in re.finditer(r':id:\s*(compl_ex_[A-Za-z0-9_]+)', rst_content):
        result['compliant_examples'].append(match.group(1))
    
    # Non-compliant example IDs
    for match in re.finditer(r':id:\s*(non_compl_ex_[A-Za-z0-9_]+)', rst_content):
        result['non_compliant_examples'].append(match.group(1))
    
    return result


# =============================================================================
# Chapter Index Management (for per-guideline file structure)
# =============================================================================

def add_include_to_chapter_index(chapter_dir: Path, guideline_id: str) -> None:
    """
    Add an include directive for a new guideline to the chapter index.
    
    Maintains alphabetical ordering by guideline ID to minimize merge conflicts.
    
    Args:
        chapter_dir: Path to the chapter directory
        guideline_id: The guideline ID to add
        
    Raises:
        FileNotFoundError: If chapter index doesn't exist
    """
    index_file = chapter_dir / "index.rst"
    
    if not index_file.exists():
        raise FileNotFoundError(f"Chapter index not found: {index_file}")
    
    content = index_file.read_text()
    
    # Check if already included (with .rst.inc extension)
    include_line = f".. include:: {guideline_id}.rst.inc"
    if include_line in content:
        print(f"  Guideline {guideline_id} already in index")
        return
    
    # Find all existing includes and their positions
    include_pattern = re.compile(
        r'^(\.\. include:: (gui_[A-Za-z0-9_]+)\.rst\.inc)$', 
        re.MULTILINE
    )
    includes = list(include_pattern.finditer(content))
    
    if not includes:
        # No existing includes - append after any content
        content = content.rstrip() + "\n\n" + include_line + "\n"
    else:
        # Find the right position to insert (alphabetical order)
        existing_ids = [(m.group(2), m.start(), m.end()) for m in includes]
        
        insert_pos = None
        for existing_id, start, end in existing_ids:
            if guideline_id < existing_id:
                insert_pos = start
                break
        
        if insert_pos is None:
            # Insert at end (after last include)
            last_end = existing_ids[-1][2]
            content = content[:last_end] + "\n" + include_line + content[last_end:]
        else:
            # Insert before the found position
            content = content[:insert_pos] + include_line + "\n" + content[insert_pos:]
    
    index_file.write_text(content)
    print(f"  Added {guideline_id} to {index_file}")


def remove_include_from_chapter_index(chapter_dir: Path, guideline_id: str) -> bool:
    """
    Remove an include directive from the chapter index.
    
    Args:
        chapter_dir: Path to the chapter directory
        guideline_id: The guideline ID to remove
        
    Returns:
        True if removed, False if not found
    """
    index_file = chapter_dir / "index.rst"
    
    if not index_file.exists():
        return False
    
    content = index_file.read_text()
    include_line = f".. include:: {guideline_id}.rst.inc\n"
    
    if include_line in content:
        content = content.replace(include_line, "")
        index_file.write_text(content)
        print(f"  Removed {guideline_id} from {index_file}")
        return True
    
    return False


# =============================================================================
# Guideline File Operations
# =============================================================================

def save_guideline_file(content: str, chapter: str, base_dir: str = DEFAULT_GUIDELINES_DIR):
    """
    Save a guideline to its own file in the chapter directory.
    
    For the new per-guideline file structure, this:
    1. Extracts the guideline ID from the content
    2. Adds the SPDX header and default-domain
    3. Writes to chapter_name/guideline_id.rst.inc
    4. Updates the chapter index to include the new guideline
    
    Note: We use .rst.inc extension so Sphinx doesn't auto-discover these files.
    They are only processed when included by the chapter index.rst.
    
    Args:
        content: The RST content for the guideline (without SPDX header)
        chapter: The chapter name (e.g., "Expressions")
        base_dir: Base directory for coding guidelines
        
    Returns:
        Path to the created guideline file
    """
    # Get guideline ID
    guideline_id = extract_guideline_id(content)
    
    # Determine paths
    chapter_dirname = chapter_to_dirname(chapter)
    chapter_dir = Path(base_dir) / chapter_dirname
    guideline_file = chapter_dir / f"{guideline_id}.rst.inc"
    
    # Ensure chapter directory exists
    chapter_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare full content with header
    full_content = GUIDELINE_FILE_HEADER + content.strip() + "\n"
    
    # Write the guideline file
    guideline_file.write_text(full_content)
    print(f"Saved guideline to {guideline_file}")
    
    # Update chapter index
    add_include_to_chapter_index(chapter_dir, guideline_id)
    
    return guideline_file


def save_guideline_file_legacy(content: str, chapter: str):
    """
    Append a guideline to a monolithic chapter file.
    
    This is the legacy behavior - appends to chapter.rst.
    Use save_guideline_file() for the new per-guideline structure.
    
    Args:
        content: The RST content to append
        chapter: The chapter name
    """
    filename = f"src/coding-guidelines/{chapter_to_filename(chapter)}.rst"
    with open(filename, "a", encoding="utf-8") as f:
        f.write(content)
    print(f"Saved guideline to {filename}")


def list_guidelines_in_chapter(
    chapter: str,
    base_dir: str = DEFAULT_GUIDELINES_DIR
) -> list:
    """
    List all guideline IDs in a chapter.
    
    Args:
        chapter: The chapter name
        base_dir: Base directory for coding guidelines
        
    Returns:
        List of guideline IDs
    """
    chapter_dirname = chapter_to_dirname(chapter)
    chapter_dir = Path(base_dir) / chapter_dirname
    
    if not chapter_dir.exists():
        return []
    
    guideline_ids = []
    for file in chapter_dir.glob("gui_*.rst.inc"):
        # Extract ID from filename (remove .rst.inc)
        guideline_id = file.stem  # gui_xxx (without .rst.inc)
        guideline_ids.append(guideline_id)
    
    return sorted(guideline_ids)
