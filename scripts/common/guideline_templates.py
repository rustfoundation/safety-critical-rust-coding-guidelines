# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

import argparse
import random
import re
import string
from textwrap import dedent, indent

# Configuration
CHARS = string.ascii_letters + string.digits
ID_LENGTH = 12

# Mapping from issue body headers to dict keys
# Changing issues fields name to snake_case (eg. 'Guideline Title' => 'guideline_title')
issue_header_map = {
    "Chapter": "chapter",
    "Guideline Title": "guideline_title",
    "Category": "category",
    "Status": "status",
    "Release Begin": "release_begin",
    "Release End": "release_end",
    "FLS Paragraph ID": "fls_id",
    "Decidability": "decidability",
    "Scope": "scope",
    "Tags": "tags",
    "Amplification": "amplification",
    "Exception(s)": "exceptions",
    "Rationale": "rationale",
    # Non-Compliant Examples (1-4)
    "Non-Compliant Example 1 - Prose": "non_compliant_ex_prose_1",
    "Non-Compliant Example 1 - Code": "non_compliant_ex_1",
    "Non-Compliant Example 2 - Prose (Optional)": "non_compliant_ex_prose_2",
    "Non-Compliant Example 2 - Code (Optional)": "non_compliant_ex_2",
    "Non-Compliant Example 3 - Prose (Optional)": "non_compliant_ex_prose_3",
    "Non-Compliant Example 3 - Code (Optional)": "non_compliant_ex_3",
    "Non-Compliant Example 4 - Prose (Optional)": "non_compliant_ex_prose_4",
    "Non-Compliant Example 4 - Code (Optional)": "non_compliant_ex_4",
    # Compliant Examples (1-4)
    "Compliant Example 1 - Prose": "compliant_ex_prose_1",
    "Compliant Example 1 - Code": "compliant_ex_1",
    "Compliant Example 2 - Prose (Optional)": "compliant_ex_prose_2",
    "Compliant Example 2 - Code (Optional)": "compliant_ex_2",
    "Compliant Example 3 - Prose (Optional)": "compliant_ex_prose_3",
    "Compliant Example 3 - Code (Optional)": "compliant_ex_3",
    "Compliant Example 4 - Prose (Optional)": "compliant_ex_prose_4",
    "Compliant Example 4 - Code (Optional)": "compliant_ex_4",
    # Bibliography (Optional)
    "Bibliography": "bibliography",
    # Legacy field names (for backwards compatibility with old issues)
    "Non-Compliant Example - Prose": "non_compliant_ex_prose_1",
    "Non-Compliant Example - Code": "non_compliant_ex_1",
    "Compliant Example - Prose": "compliant_ex_prose_1",
    "Compliant Example - Code": "compliant_ex_1",
}


def generate_id(prefix):
    """Generate a random ID with the given prefix."""
    random_part = "".join(random.choice(CHARS) for _ in range(ID_LENGTH))
    return f"{prefix}_{random_part}"


def reindent(text: str, spaces: int) -> str:
    """
    Dedent text and re-indent all lines to specified level.

    This is necessary because Pandoc conversion adds its own indentation
    to multiline content, which doesn't match the RST directive structure.
    """
    if not text or not text.strip():
        return ""
    # Remove common leading whitespace
    dedented = dedent(text).strip()
    # Re-indent all lines
    return indent(dedented, " " * spaces)


def generate_example_block(
    example_type: str,
    example_id: str,
    status: str,
    prose: str,
    code: str,
) -> str:
    """
    Generate a single example block (compliant or non-compliant).

    Args:
        example_type: Either "compliant_example" or "non_compliant_example"
        example_id: The unique ID for this example
        status: The status (e.g., "draft")
        prose: The prose description
        code: The code block content

    Returns:
        Formatted RST string for the example (indented 4 spaces to nest inside guideline)
    """
    # Properly indent multiline prose (8 spaces - inside example inside guideline)
    prose_indented = reindent(prose, 8)
    # Properly indent code (12 spaces - inside rust-example inside example inside guideline)
    code_indented = reindent(code, 12)

    return f"""
    .. {example_type}::
        :id: {example_id}
        :status: {status}

{prose_indented}

        .. rust-example::

{code_indented}
"""


def generate_bibliography_block(
    bibliography_id: str,
    guideline_id: str,
    status: str,
    entries: list,  # List of (citation_key, author, title, url) tuples
) -> str:
    """
    Generate a bibliography block.

    Args:
        bibliography_id: The unique ID for this bibliography
        guideline_id: The parent guideline ID (for namespacing citations)
        status: The status (e.g., "draft")
        entries: List of (citation_key, author, title, url) tuples

    Returns:
        Formatted RST string for the bibliography (indented 4 spaces to nest inside guideline)

    Note:
        Uses :bibentry: role for citation anchors, namespaced by guideline ID
        to avoid conflicts between guidelines using the same citation keys.
    """
    if not entries:
        return ""

    # Build the list-table content (indented 10 spaces for inside list-table inside bibliography)
    # Use :bibentry: role with guideline_id prefix for namespacing
    table_rows = []
    for citation_key, author, title, url in entries:
        if url:
            row = f"          * - :bibentry:`{guideline_id}:{citation_key}`\n            - {author}. \"{title}.\" {url}"
        else:
            row = f"          * - :bibentry:`{guideline_id}:{citation_key}`\n            - {author}. \"{title}.\""
        table_rows.append(row)

    table_content = "\n".join(table_rows)

    return f"""
    .. bibliography::
        :id: {bibliography_id}
        :status: {status}

        .. list-table::
           :header-rows: 0
           :widths: auto
           :class: bibliography-table

{table_content}
"""


def parse_bibliography_entries(bibliography_text: str) -> list:
    """
    Parse bibliography entries from text input.

    Expected format (Markdown reference link syntax):
    [CITATION-KEY]: URL "Author | Title"

    The title string contains "Author | Title" separated by a pipe.

    Examples:
    [RUST-REF-UNION]: https://doc.rust-lang.org/reference/items/unions.html "The Rust Reference | Unions"
    [CERT-C-INT34]: https://wiki.sei.cmu.edu/confluence/x/ItcxBQ "SEI CERT C | INT34-C. Do not shift by negative bits"

    Args:
        bibliography_text: Raw bibliography text from issue

    Returns:
        List of (citation_key, author, title, url) tuples
    """
    entries = []

    if not bibliography_text or not bibliography_text.strip():
        return entries

    # Pattern: [KEY]: URL "Author. Title"
    # Standard Markdown reference link syntax with author.title in the title string
    markdown_ref_pattern = re.compile(
        r'\[([A-Z][A-Z0-9-]*[A-Z0-9])\]:\s*'  # [KEY]:
        r'(https?://\S+)\s+'  # URL
        r'"([^"]+)"',  # "Author. Title"
        re.MULTILINE,
    )

    for match in markdown_ref_pattern.finditer(bibliography_text):
        key, url, author_title = match.groups()

        # Split author and title on pipe separator
        # e.g., "The Rust Reference | Unions" -> ("The Rust Reference", "Unions")
        if " | " in author_title:
            author, title = author_title.split(" | ", 1)
        elif "|" in author_title:
            # Handle case without spaces around pipe
            author, title = author_title.split("|", 1)
        else:
            # No separator found - treat whole thing as title
            author = ""
            title = author_title

        entries.append((key.strip(), author.strip(), title.strip(), url.strip()))

    if entries:
        return entries

    # Fallback: try legacy format for backwards compatibility
    # [KEY] Author. "Title." URL
    legacy_pattern = re.compile(
        r"\[([A-Z][A-Z0-9-]*[A-Z0-9])\]\s+"  # Citation key in brackets
        r'([^"]+?)\.\s+'  # Author (non-greedy, ends with period + space)
        r'"([^"]+)"\s+'  # Title in quotes (may include period inside)
        r"(https?://\S+)",  # URL
        re.MULTILINE,
    )

    for match in legacy_pattern.finditer(bibliography_text):
        key, author, title, url = match.groups()
        # Strip trailing period from title if present
        title = title.rstrip(".")
        entries.append((key.strip(), author.strip(), title.strip(), url.strip()))

    return entries


def guideline_rst_template(
    guideline_title: str,
    category: str,
    status: str,
    release_begin: str,
    release_end: str,
    fls_id: str,
    decidability: str,
    scope: str,
    tags: str,
    amplification: str,
    exceptions: str,
    rationale: str,
    non_compliant_examples: list,  # List of (prose, code) tuples
    compliant_examples: list,  # List of (prose, code) tuples
    bibliography_entries: list = None,  # List of (key, author, title, url) tuples
) -> str:
    """
    Generate a .rst guideline entry from field values.

    Args:
        non_compliant_examples: List of (prose, code) tuples for non-compliant examples
        compliant_examples: List of (prose, code) tuples for compliant examples
        bibliography_entries: Optional list of (key, author, title, url) tuples
    """

    # Generate unique IDs
    guideline_id = generate_id("gui")
    rationale_id = generate_id("rat")

    # Normalize inputs
    def norm(value: str) -> str:
        return value.strip().lower()

    # Build optional exception section
    exception_section = ""
    if exceptions and exceptions.strip():
        # Properly indent exceptions content (4 spaces inside guideline directive)
        indented_exceptions = reindent(exceptions, 4)
        exception_section = f"""    **Exceptions**

{indented_exceptions}"""

    # Generate non-compliant example blocks
    non_compliant_blocks = []
    for i, (prose, code) in enumerate(non_compliant_examples):
        if prose.strip() and code.strip():
            example_id = generate_id("non_compl_ex")
            block = generate_example_block(
                "non_compliant_example",
                example_id,
                norm(status),
                prose,
                code,
            )
            non_compliant_blocks.append(block)

    # Generate compliant example blocks
    compliant_blocks = []
    for i, (prose, code) in enumerate(compliant_examples):
        if prose.strip() and code.strip():
            example_id = generate_id("compl_ex")
            block = generate_example_block(
                "compliant_example",
                example_id,
                norm(status),
                prose,
                code,
            )
            compliant_blocks.append(block)

    # Generate bibliography block if entries provided
    bibliography_block = ""
    if bibliography_entries:
        bibliography_id = generate_id("bib")
        bibliography_block = generate_bibliography_block(
            bibliography_id,
            guideline_id,
            norm(status),
            bibliography_entries,
        )

    # Combine all example blocks
    all_examples = "\n".join(non_compliant_blocks + compliant_blocks)

    # Add bibliography if present
    if bibliography_block:
        all_examples += "\n" + bibliography_block

    # Properly indent multiline content:
    # - Amplification: 4 spaces (inside guideline directive)
    # - Rationale: 8 spaces (inside rationale inside guideline)
    amplification_indented = reindent(amplification, 4)
    rationale_indented = reindent(rationale, 8)

    # Exception section is already properly indented, preserve it
    exception_block = ""
    if exception_section:
        exception_block = "\n" + exception_section + "\n"

    # Build the guideline text
    guideline_text = f"""
.. guideline:: {guideline_title.strip()}
    :id: {guideline_id}
    :category: {norm(category)}
    :status: {norm(status)}
    :release: {norm(release_begin)}-{release_end.strip()}
    :fls: {norm(fls_id)}
    :decidability: {norm(decidability)}
    :scope: {norm(scope)}
    :tags: {tags}

{amplification_indented}
{exception_block}
    .. rationale::
        :id: {rationale_id}
        :status: {norm(status)}

{rationale_indented}
{all_examples}
"""

    return guideline_text


def generate_guideline_template(
    num_non_compliant: int = 1,
    num_compliant: int = 1,
    include_bibliography: bool = False,
    num_bib_entries: int = 1,
):
    """
    Generate a complete guideline template with all required sections.

    Args:
        num_non_compliant: Number of non-compliant examples to include (1-4)
        num_compliant: Number of compliant examples to include (1-4)
        include_bibliography: Whether to include a bibliography section
        num_bib_entries: Number of bibliography entries to include (1-5)
    """
    # Clamp to valid range
    num_non_compliant = max(1, min(4, num_non_compliant))
    num_compliant = max(1, min(4, num_compliant))
    num_bib_entries = max(1, min(5, num_bib_entries))

    # Generate non-compliant examples
    non_compliant_examples = []
    for i in range(1, num_non_compliant + 1):
        non_compliant_examples.append(
            (
                f"Explanation of non-compliant example {i}.",
                f"fn non_compliant_example_{i}() {{\n    // Non-compliant implementation {i}\n}}",
            )
        )

    # Generate compliant examples
    compliant_examples = []
    for i in range(1, num_compliant + 1):
        compliant_examples.append(
            (
                f"Explanation of compliant example {i}.",
                f"fn compliant_example_{i}() {{\n    // Compliant implementation {i}\n}}",
            )
        )

    # Generate bibliography entries if requested
    bibliography_entries = None
    if include_bibliography:
        bibliography_entries = []
        for i in range(1, num_bib_entries + 1):
            bibliography_entries.append(
                (
                    f"REF-KEY-{i}",
                    f"Author {i}",
                    f"Reference Title {i}",
                    f"https://example.com/ref{i}",
                )
            )

    template = guideline_rst_template(
        guideline_title="Title Here",
        category="",
        status="draft",
        release_begin="",
        release_end="",
        fls_id="",
        decidability="",
        scope="",
        tags="",
        amplification="Description of the guideline goes here.",
        exceptions="",
        rationale="Explanation of why this guideline is important.",
        non_compliant_examples=non_compliant_examples,
        compliant_examples=compliant_examples,
        bibliography_entries=bibliography_entries,
    )
    return template


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate guideline templates with randomly generated IDs"
    )
    parser.add_argument(
        "-n",
        "--number-of-templates",
        type=int,
        default=1,
        help="Number of templates to generate (default: 1)",
    )
    parser.add_argument(
        "--non-compliant",
        type=int,
        default=1,
        choices=[1, 2, 3, 4],
        help="Number of non-compliant examples to include (default: 1, max: 4)",
    )
    parser.add_argument(
        "--compliant",
        type=int,
        default=1,
        choices=[1, 2, 3, 4],
        help="Number of compliant examples to include (default: 1, max: 4)",
    )
    parser.add_argument(
        "--bibliography",
        action="store_true",
        help="Include a bibliography section in the template",
    )
    parser.add_argument(
        "--bib-entries",
        type=int,
        default=1,
        choices=[1, 2, 3, 4, 5],
        help="Number of bibliography entries to include (default: 1, max: 5)",
    )
    return parser.parse_args()


def main():
    """Generate the specified number of guideline templates."""
    args = parse_args()
    num_templates = args.number_of_templates

    for i in range(num_templates):
        if num_templates > 1:
            print(f"=== Template {i + 1} ===\n")

        template = generate_guideline_template(
            num_non_compliant=args.non_compliant,
            num_compliant=args.compliant,
            include_bibliography=args.bibliography,
            num_bib_entries=args.bib_entries,
        )
        print(template)

        if num_templates > 1 and i < num_templates - 1:
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
