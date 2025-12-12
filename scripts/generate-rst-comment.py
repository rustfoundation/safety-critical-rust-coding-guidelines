#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
This script generates a GitHub comment containing the RST preview of a coding guideline.
It reads a GitHub issue JSON from stdin and outputs a formatted Markdown comment.

Usage:
    cat issue.json | uv run python scripts/generate-rst-comment.py
    curl https://api.github.com/repos/.../issues/123 | uv run python scripts/generate-rst-comment.py
"""

import json
import os
import re
import sys

# Add the scripts directory to Python path so we can import guideline_utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from guideline_utils import (
    chapter_to_filename,
    extract_form_fields,
    guideline_template,
    normalize_list_separation,
    normalize_md,
)


def extract_guideline_id(rst_content: str) -> str:
    """
    Extract the guideline ID from RST content.
    
    Args:
        rst_content: The generated RST content
        
    Returns:
        The guideline ID (e.g., "gui_abc123XYZ") or empty string if not found
    """
    match = re.search(r':id:\s*(gui_[a-zA-Z0-9]+)', rst_content)
    return match.group(1) if match else ""


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
    guideline_id = extract_guideline_id(rst_content)
    
    # Determine target path based on whether we have a guideline ID
    if guideline_id:
        target_dir = f"src/coding-guidelines/{chapter_slug}/"
        target_file = f"{target_dir}{guideline_id}.rst.inc"
        file_instructions = f"""
### 📁 Target Location

Create a new file: `{target_file}`

> **Note:** The `.rst.inc` extension prevents Sphinx from auto-discovering the file.
> It will be included via the chapter's `index.rst`."""
    else:
        # Fallback for legacy structure (shouldn't happen with new template)
        target_file = f"src/coding-guidelines/{chapter_slug}.rst"
        file_instructions = f"""
### 📁 Target File

Add this guideline to: `{target_file}`"""
    
    comment = f"""## 📋 RST Preview for Coding Guideline

This is an automatically generated preview of your coding guideline in reStructuredText format.
{file_instructions}

### 📝 How to Use This

**Option A: Automatic (Recommended)**

Once this issue is approved, a maintainer will add the `sign-off: create pr from issue` label, which automatically creates a PR with the guideline file.

**Option B: Manual**

1. **Fork the repository** (if you haven't already) and clone it locally
2. **Create a new branch** from `main`:
   ```bash
   git checkout main
   git pull origin main
   git checkout -b guideline/your-descriptive-branch-name
   ```
3. **Create the guideline file**:
   ```bash
   mkdir -p src/coding-guidelines/{chapter_slug}
   ```
4. **Copy the RST content** below into a new file named `{guideline_id}.rst.inc`
5. **Update the chapter index** - Add an include directive to `src/coding-guidelines/{chapter_slug}/index.rst`:
   ```rst
   .. include:: {guideline_id}.rst.inc
   ```
   Keep the includes in alphabetical order by guideline ID.
6. **Build locally** to verify the guideline renders correctly:
   ```bash
   ./make.py
   ```
7. **Commit and push** your changes:
   ```bash
   git add src/coding-guidelines/{chapter_slug}/
   git commit -m "Add guideline: <your guideline title>"
   git push origin guideline/your-descriptive-branch-name
   ```
8. **Open a Pull Request** against `main`

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
