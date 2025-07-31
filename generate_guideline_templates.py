#!/usr/bin/env -S uv run
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

import argparse
import string
import random
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
    "Non-Compliant Example - Prose": "non_compliant_ex_prose",
    "Non-Compliant Example - Code": "non_compliant_ex",
    "Compliant Example - Prose": "compliant_example_prose",
    "Compliant Example - Code": "compliant_example",
}


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
    rationale: str,
    non_compliant_ex_prose: str,
    non_compliant_ex: str,
    compliant_example_prose: str,
    compliant_example: str,
) -> str:
    """
    Generate a .rst guideline entry from field values.
    """

    # Generate unique IDs
    guideline_id = generate_id("gui")
    rationale_id = generate_id("rat")
    non_compliant_example_id = generate_id("non_compl_ex")
    compliant_example_id = generate_id("compl_ex")

    # Normalize inputs
    def norm(value: str) -> str:
        return value.strip().lower()

    indented_compliant_ex = indent(compliant_example.strip(), " " * 13)
    indented_non_compliant_ex = indent(non_compliant_ex.strip(), " " * 13)
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

            .. rationale:: 
                :id: {rationale_id} 
                :status: {norm(status)}

                {rationale.strip()}

            .. non_compliant_example::
                :id: {non_compliant_example_id} 
                :status: {norm(status)}

                {non_compliant_ex_prose.strip()}
            
                .. code-block:: rust
                
                    {indented_non_compliant_ex.strip()}

            .. compliant_example::
                :id: {compliant_example_id} 
                :status: {norm(status)}

                {compliant_example_prose.strip()}
            
                .. code-block:: rust
                
                    {indented_compliant_ex.strip()}
    """)

    return guideline_text


def generate_id(prefix):
    """Generate a random ID with the given prefix."""
    random_part = "".join(random.choice(CHARS) for _ in range(ID_LENGTH))
    return f"{prefix}_{random_part}"


def generate_guideline_template():
    """Generate a complete guideline template with all required sections."""
    # Generate IDs for all sections
    guideline_id = generate_id("gui")
    rationale_id = generate_id("rat")
    non_compliant_example_id = generate_id("non_compl_ex")
    compliant_example_id = generate_id("compl_ex")

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
        rationale="Explanation of why this guideline is important.",
        non_compliant_ex_prose="Explanation of code example.",
        non_compliant_ex=""" fn example_function() {\n          // Non-compliant implementation\n       } """,
        compliant_example_prose="Explanation of code example.",
        compliant_example=""" fn example_function() {\n          // Compliant implementation\n       } """,
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
    return parser.parse_args()


def main():
    """Generate the specified number of guideline templates."""
    args = parse_args()
    num_templates = args.number_of_templates

    for i in range(num_templates):
        if num_templates > 1:
            print(f"=== Template {i + 1} ===\n")

        template = generate_guideline_template()
        print(template)

        if num_templates > 1 and i < num_templates - 1:
            print("\n" + "=" * 80 + "\n")


if __name__ == "__main__":
    main()
