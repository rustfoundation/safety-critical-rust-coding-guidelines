# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Shared utilities for parsing GitHub issues and generating RST guideline content.

This module contains common functions used by:
- guideline-from-issue.py (for issue JSON to RST conversion)
- generate-rst-comment.py (for generating preview comments)
"""

import re
from pathlib import Path
from textwrap import dedent, indent
from typing import Optional

import pypandoc

from scripts.common.guideline_pages import (
    build_guideline_page_content,
    extract_guideline_title,
)
from scripts.common.guideline_templates import (
    guideline_rst_template,
    issue_header_map,
    parse_bibliography_entries,
)

# =============================================================================
# Constants for per-guideline file structure
# =============================================================================

# Default guidelines directory
DEFAULT_GUIDELINES_DIR = Path("src/coding-guidelines")

# Pattern to match citation references in Markdown: [CITATION-KEY]
# Citation keys must be UPPERCASE-WITH-HYPHENS
MARKDOWN_CITATION_PATTERN = re.compile(
    r'\[([A-Z][A-Z0-9-]*[A-Z0-9])\]'
)

# Pattern to avoid matching URLs or other bracket content
# This helps distinguish citations from links like [text](url)
MARKDOWN_LINK_PATTERN = re.compile(
    r'\[([^\]]+)\]\([^)]+\)'
)

GUIDELINE_TOCTREE_BLOCK = """.. toctree::
   :maxdepth: 1
   :titlesonly:
   :glob:

   gui_*
"""


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
# Citation reference utilities
# =============================================================================

def extract_citation_references(text: str) -> list:
    """
    Extract all citation references from Markdown text.
    
    Citation references are in the format [CITATION-KEY] where CITATION-KEY
    is UPPERCASE-WITH-HYPHENS.
    
    Args:
        text: Markdown text to search
        
    Returns:
        List of citation keys found (without brackets)
    """
    # First, remove markdown links to avoid false positives
    # [text](url) should not match as a citation
    text_without_links = MARKDOWN_LINK_PATTERN.sub('', text)
    
    # Find all citation references
    citations = MARKDOWN_CITATION_PATTERN.findall(text_without_links)
    
    # Return unique citations while preserving order
    seen = set()
    unique_citations = []
    for citation in citations:
        if citation not in seen:
            seen.add(citation)
            unique_citations.append(citation)
    
    return unique_citations


def convert_citations_to_rst(text: str, guideline_id: str) -> str:
    """
    Convert Markdown citation references [KEY] to RST :cite: roles.
    
    Args:
        text: Text that may contain Markdown citation references
        guideline_id: The guideline ID for namespacing citations
        
    Returns:
        Text with [KEY] converted to :cite:`gui_xxx:KEY`
    """
    if not guideline_id:
        return text
    
    def replace_citation(match):
        # Get the full match to check if it's part of a markdown link
        full_text = match.string
        
        # Check if this is part of a markdown link [text](url)
        # by looking for a '(' immediately after the ']'
        end = match.end()
        if end < len(full_text) and full_text[end] == '(':
            # This is a markdown link, don't replace
            return match.group(0)
        
        citation_key = match.group(1)
        return f':cite:`{guideline_id}:{citation_key}`'
    
    return MARKDOWN_CITATION_PATTERN.sub(replace_citation, text)


def validate_citation_references(
    text: str,
    bibliography_keys: set
) -> tuple:
    """
    Validate that all citation references in text have matching bibliography entries.
    
    Args:
        text: Text to check for citation references
        bibliography_keys: Set of valid citation keys from bibliography
        
    Returns:
        Tuple of (is_valid, list of undefined citation keys)
    """
    citations = extract_citation_references(text)
    undefined = [c for c in citations if c not in bibliography_keys]
    return (len(undefined) == 0, undefined)


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
# Bibliography utilities
# =============================================================================

def validate_bibliography_entry(entry: tuple) -> tuple:
    """
    Validate a single bibliography entry.
    
    Args:
        entry: Tuple of (citation_key, author, title, url)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    key, author, title, url = entry
    
    # Validate citation key format
    key_pattern = re.compile(r'^[A-Z][A-Z0-9-]*[A-Z0-9]$')
    if not key_pattern.match(key):
        return False, f"Invalid citation key format: '{key}'. Expected UPPERCASE-WITH-HYPHENS"
    
    if len(key) > 50:
        return False, f"Citation key '{key}' exceeds 50 character limit"
    
    # Validate URL format (basic check)
    if url and not url.startswith(('http://', 'https://')):
        return False, f"Invalid URL format: '{url}'. Must start with http:// or https://"
    
    return True, ""


def format_bibliography_rst(entries: list, bibliography_id: str, guideline_id: str, status: str = "draft") -> str:
    """
    Format bibliography entries as RST.
    
    Args:
        entries: List of (citation_key, author, title, url) tuples
        bibliography_id: The unique ID for this bibliography
        guideline_id: The parent guideline ID (for namespacing citations)
        status: The status (e.g., "draft")
        
    Returns:
        Formatted RST string for the bibliography
    
    Note:
        Uses :bibentry: role for citation anchors, namespaced by guideline ID
        to avoid conflicts between guidelines using the same citation keys.
    """
    if not entries:
        return ""
    
    # Build the list-table content
    # Use :bibentry: role with guideline_id prefix for namespacing
    table_rows = []
    for citation_key, author, title, url in entries:
        if url:
            row = f"      * - :bibentry:`{guideline_id}:{citation_key}`\n        - {author}. \"{title}.\" {url}"
        else:
            row = f"      * - :bibentry:`{guideline_id}:{citation_key}`\n        - {author}. \"{title}.\""
        table_rows.append(row)
    
    table_content = "\n".join(table_rows)
    
    return dedent(f"""
            .. bibliography::
                :id: {bibliography_id}
                :status: {status}

                .. list-table::
                   :header-rows: 0
                   :widths: auto
                   :class: bibliography-table

{table_content}
    """)


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


def collect_examples(fields: dict, example_type: str) -> list:
    """
    Collect all examples of a given type from fields.

    Args:
        fields: Dictionary of form fields
        example_type: Either "non_compliant" or "compliant"

    Returns:
        List of (prose, code) tuples for non-empty examples
    """
    examples = []

    # Map the example type to field prefixes
    if example_type == "non_compliant":
        prose_prefix = "non_compliant_ex_prose_"
        code_prefix = "non_compliant_ex_"
    else:  # compliant
        prose_prefix = "compliant_ex_prose_"
        code_prefix = "compliant_ex_"

    # Check for examples 1-4
    for i in range(1, 5):
        prose_key = f"{prose_prefix}{i}"
        code_key = f"{code_prefix}{i}"

        prose = fields.get(prose_key, "").strip()
        code = fields.get(code_key, "").strip()

        # Only include if both prose and code are non-empty
        if prose and code:
            examples.append((prose, code))

    return examples


def guideline_template(fields: dict) -> str:
    """
    Convert a dictionary of guideline fields into proper RST format.
    
    This function:
    1. Converts Markdown to RST
    2. Converts citation references [KEY] to :cite:`gui_xxx:KEY` roles
    3. Generates the complete guideline RST structure

    Args:
        fields: Dictionary containing all guideline fields

    Returns:
        Formatted RST string for the guideline
    """
    def get(key):
        return fields.get(key, "").strip()

    # First, generate a temporary guideline ID for citation conversion
    # This will be replaced by the actual ID in guideline_rst_template
    import random
    import string
    temp_id = "gui_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(12))
    
    # Parse bibliography entries first to know what citation keys are available
    bibliography_raw = get("bibliography")
    bibliography_entries = None
    if bibliography_raw:
        bibliography_entries = parse_bibliography_entries(bibliography_raw)
        # Validate entries
        for entry in bibliography_entries:
            is_valid, error_msg = validate_bibliography_entry(entry)
            if not is_valid:
                # Log warning but continue - the preview will show the issue
                print(f"Warning: {error_msg}")

    # Convert and process amplification
    # Note: Citation conversion must happen AFTER md_to_rst to avoid Pandoc escaping backticks
    amplification_md = get("amplification")
    amplification_rst = md_to_rst(amplification_md)
    amplification_with_citations = convert_citations_to_rst(amplification_rst, temp_id)
    amplification_text = indent(amplification_with_citations, " " * 12)

    # Convert and process rationale
    rationale_md = get("rationale")
    rationale_rst = md_to_rst(rationale_md)
    rationale_with_citations = convert_citations_to_rst(rationale_rst, temp_id)
    rationale_text = indent(rationale_with_citations, " " * 16)

    # Process exceptions field - convert MD to RST and pre-indent for multi-line support
    exceptions_raw = get("exceptions")
    exceptions_text = ""
    if exceptions_raw:
        exceptions_rst = md_to_rst(exceptions_raw)
        exceptions_with_citations = convert_citations_to_rst(exceptions_rst, temp_id)
        exceptions_text = indent(exceptions_with_citations, " " * 12)

    # Collect non-compliant examples
    non_compliant_examples = []
    for prose, code in collect_examples(fields, "non_compliant"):
        # Convert citations in prose (after MD->RST conversion)
        prose_rst = md_to_rst(prose)
        prose_with_citations = convert_citations_to_rst(prose_rst, temp_id)
        prose_indented = indent(prose_with_citations, " " * 16)
        code_formatted = format_code_block(code)
        non_compliant_examples.append((prose_indented, code_formatted))

    # Collect compliant examples
    compliant_examples = []
    for prose, code in collect_examples(fields, "compliant"):
        # Convert citations in prose (after MD->RST conversion)
        prose_rst = md_to_rst(prose)
        prose_with_citations = convert_citations_to_rst(prose_rst, temp_id)
        prose_indented = indent(prose_with_citations, " " * 16)
        code_formatted = format_code_block(code)
        compliant_examples.append((prose_indented, code_formatted))

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
        non_compliant_examples=non_compliant_examples,
        compliant_examples=compliant_examples,
        bibliography_entries=bibliography_entries,
    )

    # Replace the temporary ID with the actual generated ID
    # The guideline_rst_template generates a new ID, so we need to extract it
    # and update all the temporary citations
    actual_id_match = re.search(r':id:\s*(gui_[a-zA-Z0-9]+)', guideline_text)
    if actual_id_match:
        actual_id = actual_id_match.group(1)
        guideline_text = guideline_text.replace(temp_id, actual_id)

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
        Dictionary with keys 'guideline', 'rationale', 'compliant', 'non_compliant', 'bibliography'
    """
    ids = {
        'guideline': '',
        'rationale': '',
        'compliant': [],
        'non_compliant': [],
        'bibliography': '',
    }

    # Guideline ID
    match = re.search(r':id:\s*(gui_[a-zA-Z0-9]+)', content)
    if match:
        ids['guideline'] = match.group(1)

    # Rationale ID
    match = re.search(r':id:\s*(rat_[a-zA-Z0-9]+)', content)
    if match:
        ids['rationale'] = match.group(1)

    # Bibliography ID
    match = re.search(r':id:\s*(bib_[a-zA-Z0-9]+)', content)
    if match:
        ids['bibliography'] = match.group(1)

    # Compliant example IDs (multiple)
    for match in re.finditer(r':id:\s*(compl_ex_[a-zA-Z0-9]+)', content):
        ids['compliant'].append(match.group(1))

    # Non-compliant example IDs (multiple)
    for match in re.finditer(r':id:\s*(non_compl_ex_[a-zA-Z0-9]+)', content):
        ids['non_compliant'].append(match.group(1))

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

def has_guideline_toctree(content: str) -> bool:
    """
    Check whether a chapter index already lists guideline pages.
    """
    in_toctree = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(".. toctree::"):
            in_toctree = True
            continue
        if in_toctree:
            if not stripped or stripped.startswith(":"):
                continue
            if line.startswith(" "):
                if stripped.startswith("gui_"):
                    return True
                continue
            in_toctree = False
    return False


def ensure_guideline_toctree(
    chapter_dir: Path,
) -> bool:
    """
    Ensure a chapter index uses a toctree for guideline pages.

    Args:
        chapter_dir: Path to the chapter directory

    Returns:
        True if successful, False otherwise
    """
    index_path = chapter_dir / "index.rst"

    if not index_path.exists():
        print(f"Warning: Index file not found: {index_path}")
        return False

    content = index_path.read_text()
    new_content = content.rstrip() + "\n"

    if not has_guideline_toctree(new_content):
        new_content = new_content.rstrip() + "\n\n" + GUIDELINE_TOCTREE_BLOCK

    if new_content != content:
        index_path.write_text(new_content)

    return True


# =============================================================================
# File operations
# =============================================================================

def save_guideline_file(
    content: str,
    chapter: str,
    guidelines_dir: Optional[Path] = None,
) -> Path:
    """
    Save a guideline to a per-guideline file in the chapter directory.

    This creates:
    1. The chapter directory if it doesn't exist
    2. A new file named {guideline_id}.rst
    3. Ensures the chapter's index.rst lists guideline pages via a toctree

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

    guideline_title = extract_guideline_title(content) or f"Guideline {guideline_id}"
    guideline_filename = f"{guideline_id}.rst"
    guideline_path = chapter_dir / guideline_filename
    full_content = build_guideline_page_content(guideline_title, content)
    guideline_path.write_text(full_content)
    print(f"Created guideline file: {guideline_path}")

    # Update the chapter index
    if ensure_guideline_toctree(chapter_dir):
        print(f"Updated index: {chapter_dir / 'index.rst'}")

    return guideline_path


def save_guideline_file_legacy(
    content: str,
    chapter: str,
    guidelines_dir: Optional[Path] = None,
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

    for file_path in chapter_dir.glob("gui_*.rst"):
        guideline_id = file_path.stem
        guidelines.append(guideline_id)

    return sorted(guidelines)
