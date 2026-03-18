# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

import re

GUIDELINE_FILE_HEADER = """\
.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

"""

GUIDELINE_TITLE_PATTERN = re.compile(
    r"^\s*\.\.\s+guideline::\s*(.*?)\s*$",
    re.MULTILINE,
)


def extract_guideline_title(content: str) -> str:
    """
    Extract the guideline title from the guideline directive.

    Args:
        content: RST content containing a guideline directive

    Returns:
        Guideline title or empty string if not found
    """
    match = GUIDELINE_TITLE_PATTERN.search(content)
    return match.group(1).strip() if match else ""


def build_guideline_page_content(title: str, guideline_body: str) -> str:
    """
    Build the full guideline page content.

    Args:
        title: Guideline title to use for the page heading
        guideline_body: Guideline directive content (without the file header)

    Returns:
        Full guideline page content as a string
    """
    body = guideline_body.strip()
    underline = "=" * len(title)
    return "\n".join(
        [
            GUIDELINE_FILE_HEADER.rstrip(),
            "",
            title,
            underline,
            "",
            body,
            "",
        ]
    )
