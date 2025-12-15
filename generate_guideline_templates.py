#!/usr/bin/env -S uv run
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

import argparse
import random
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
        Formatted RST string for the example
    """
    indented_code = indent(code.strip(), " " * 13)

    return dedent(f"""
            .. {example_type}::
                :id: {example_id}
                :status: {status}

                {prose.strip()}

                .. rust-example::

                    {indented_code.strip()}
    """)


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
    compliant_examples: list,      # List of (prose, code) tuples
) -> str:
    """
    Generate a .rst guideline entry from field values.

    Args:
        non_compliant_examples: List of (prose, code) tuples for non-compliant examples
        compliant_examples: List of (prose, code) tuples for compliant examples
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
        exception_section = f"""
            **Exceptions**

            {exceptions.strip()}
        """

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

    # Combine all example blocks
    all_examples = "\n".join(non_compliant_blocks + compliant_blocks)

    guideline_text = dedent(f"""
        .. guideline:: {guideline_title.strip()}
            :id: {guideline_id}
            :category: {norm(category)}
            :status: {norm(status)}
            :release: {norm(release_begin)}-{release_end.strip()}
            :fls: {norm(fls_id)}
            :decidability: {norm(decidability)}
            :scope: {norm(scope)}
            :tags: {tags}

            {amplification.strip()}

            {exception_section.strip()}

            .. rationale::
                :id: {rationale_id}
                :status: {norm(status)}

                {rationale.strip()}
{all_examples}
    """)

    return guideline_text


def generate_guideline_template(num_non_compliant: int = 1, num_compliant: int = 1):
    """
    Generate a complete guideline template with all required sections.

    Args:
        num_non_compliant: Number of non-compliant examples to include (1-4)
        num_compliant: Number of compliant examples to include (1-4)
    """
    # Clamp to valid range
    num_non_compliant = max(1, min(4, num_non_compliant))
    num_compliant = max(1, min(4, num_compliant))

    # Generate non-compliant examples
    non_compliant_examples = []
    for i in range(1, num_non_compliant + 1):
        non_compliant_examples.append((
            f"Explanation of non-compliant example {i}.",
            f"fn non_compliant_example_{i}() {{\n    // Non-compliant implementation {i}\n}}"
        ))

    # Generate compliant examples
    compliant_examples = []
    for i in range(1, num_compliant + 1):
        compliant_examples.append((
            f"Explanation of compliant example {i}.",
            f"fn compliant_example_{i}() {{\n    // Compliant implementation {i}\n}}"
        ))

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
        )
        print(template)

        if num_templates > 1 and i < num_templates - 1:
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
