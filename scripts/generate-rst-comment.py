#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
This script generates a GitHub comment containing the RST preview of a coding guideline.
It reads a GitHub issue JSON from stdin and outputs a formatted Markdown comment.

Usage:
    cat issue.json | uv run python scripts/generate-rst-comment.py
    curl https://api.github.com/repos/.../issues/123 | uv run python scripts/generate-rst-comment.py

Location: scripts/generate-rst-comment.py (new file)
"""

import json
import sys

from guideline_utils import (
    extract_form_fields,
    guideline_template,
    normalize_md,
    normalize_list_separation,
    chapter_to_filename,
)


def generate_comment(rst_content: str, chapter: str) -> str:
    """
    Generate a formatted GitHub comment with instructions and RST content.
    
    Args:
        rst_content: The generated RST content for the guideline
        chapter: The chapter name (e.g., "Concurrency", "Expressions")
    
    Returns:
        Formatted Markdown comment string
    """
    chapter_slug = chapter_to_filename(chapter)
    target_file = f"src/coding-guidelines/{chapter_slug}.rst"
    
    comment = f"""## 📋 RST Preview for Coding Guideline

This is an automatically generated preview of your coding guideline in reStructuredText format.

### 📁 Target File

Add this guideline to: `{target_file}`

### 📝 How to Use This

1. **Fork the repository** (if you haven't already) and clone it locally
2. **Create a new branch** from `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b guideline/your-descriptive-branch-name
   ```
3. **Open the target file** `{target_file}` in your editor
4. **Copy the RST content** below and paste it at the end of the file (before any final directives if present)
5. **Build locally** to verify the guideline renders correctly:
   ```bash
   ./make.py
   ```
6. **Commit and push** your changes:
   ```bash
   git add {target_file}
   git commit -m "Add guideline: <your guideline title>"
   git push origin guideline/your-descriptive-branch-name
   ```
7. **Open a Pull Request** against `main`

<details>
<summary><strong>📄 Click to expand RST content</strong></summary>

```rst
{rst_content}
```

</details>

---
<sub>🤖 This comment was automatically generated from the issue content. It will be updated when you edit the issue body.</sub>

<!-- rst-preview-comment -->
"""
    return comment


def main():
    # Read JSON from stdin
    stdin_issue_json = sys.stdin.read()
    json_issue = json.loads(stdin_issue_json)

    issue_body = json_issue["body"]
    issue_body = normalize_md(issue_body)
    issue_body = normalize_list_separation(issue_body)

    fields = extract_form_fields(issue_body)
    chapter = fields["chapter"]
    
    # Generate RST content
    rst_content = guideline_template(fields)
    
    # Generate the comment
    comment = generate_comment(rst_content.strip(), chapter)
    
    print(comment)


if __name__ == "__main__":
    main()
