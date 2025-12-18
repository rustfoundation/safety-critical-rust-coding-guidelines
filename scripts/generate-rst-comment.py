#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
This script generates a GitHub comment containing the RST preview of a coding guideline.
It reads a GitHub issue JSON from stdin and outputs a formatted Markdown comment.

It also extracts and tests Rust code examples, reporting any compilation failures.

Usage:
    cat issue.json | uv run python scripts/generate-rst-comment.py
    curl https://api.github.com/repos/.../issues/123 | uv run python scripts/generate-rst-comment.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Tuple

# Add the scripts directory to Python path so we can import guideline_utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from guideline_utils import (
    chapter_to_filename,
    collect_examples,
    extract_form_fields,
    guideline_template,
    normalize_list_separation,
    normalize_md,
)

# SPDX header to prepend to guideline files
GUIDELINE_FILE_HEADER = """\
.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""


@dataclass
class CodeTestResult:
    """Result of testing a single code example."""
    example_type: str  # "compliant" or "non_compliant"
    example_number: int
    passed: bool
    error_message: str = ""
    compiler_output: str = ""


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


def strip_markdown_fences(code: str) -> str:
    """
    Remove markdown code fences from code if present.

    Args:
        code: Code possibly wrapped in ```rust ... ```

    Returns:
        Code without fences
    """
    lines = code.strip().splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
    return "\n".join(lines)


def process_hidden_lines(code: str) -> str:
    """
    Process rustdoc-style hidden lines.
    Lines starting with '# ' have the marker removed for compilation.

    Args:
        code: Code with potential hidden line markers

    Returns:
        Code ready for compilation
    """
    lines = []
    for line in code.split('\n'):
        if line.startswith('# '):
            # Hidden line - include without the marker
            lines.append(line[2:])
        elif line == '#':
            # Empty hidden line
            lines.append('')
        else:
            lines.append(line)
    return '\n'.join(lines)


def wrap_in_main(code: str) -> str:
    """
    Wrap code in a main function if it doesn't have one.
    """
    # Check if code already has a main function
    if re.search(r'\bfn\s+main\s*\(', code):
        return code

    # Check if it has any function definitions or other top-level items
    has_functions = re.search(r'\bfn\s+\w+\s*[<(]', code)
    has_impl = re.search(r'\bimpl\b', code)
    has_struct = re.search(r'\bstruct\b', code)
    has_enum = re.search(r'\benum\b', code)
    has_trait = re.search(r'\btrait\b', code)
    has_mod = re.search(r'\bmod\b', code)
    has_type = re.search(r'\btype\b', code)

    # If it looks like top-level items, don't wrap
    if has_functions or has_impl or has_struct or has_enum or has_trait or has_mod or has_type:
        return code

    # Check for use/const/static statements
    has_use = re.search(r'\buse\b', code)
    has_const = re.search(r'\bconst\b', code)
    has_static = re.search(r'\bstatic\b', code)

    if has_use or has_const or has_static:
        # Keep use/const/static at top level, wrap the rest
        lines = code.split('\n')
        top_level = []
        body = []
        in_top_level = True

        for line in lines:
            stripped = line.strip()
            if in_top_level and (stripped.startswith('use ') or 
                                  stripped.startswith('const ') or 
                                  stripped.startswith('static ')):
                top_level.append(line)
            else:
                in_top_level = False
                body.append(line)

        if body:
            indented_body = '\n'.join('    ' + line if line.strip() else '' for line in body)
            return '\n'.join(top_level) + '\n\nfn main() {\n' + indented_body + '\n}'
        else:
            return '\n'.join(top_level) + '\n\nfn main() {}'

    # Simple case: wrap everything
    indented = '\n'.join('    ' + line if line.strip() else '' for line in code.split('\n'))
    return 'fn main() {\n' + indented + '\n}'


def test_rust_code(code: str, timeout: int = 30) -> Tuple[bool, str]:
    """
    Test if Rust code compiles successfully.

    Args:
        code: Rust code to test
        timeout: Compilation timeout in seconds

    Returns:
        Tuple of (passed, error_message)
    """
    # Strip markdown fences if present
    code = strip_markdown_fences(code)

    # Process hidden lines
    code = process_hidden_lines(code)

    # Wrap in main if needed
    code = wrap_in_main(code)

    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = os.path.join(tmpdir, "test.rs")
        out_file = os.path.join(tmpdir, "test_binary")

        with open(src_file, "w") as f:
            f.write(code)

        try:
            result = subprocess.run(
                ["rustc", "--edition=2021", "--crate-type=bin", "-o", out_file, src_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                return True, ""
            else:
                # Extract key error info
                error_lines = result.stderr.strip().split('\n')
                # Get first few relevant error lines
                relevant_errors = []
                for line in error_lines[:15]:
                    if line.strip():
                        relevant_errors.append(line)
                return False, "\n".join(relevant_errors)

        except subprocess.TimeoutExpired:
            return False, "Compilation timed out"
        except FileNotFoundError:
            return False, "rustc not found - cannot test code"
        except Exception as e:
            return False, f"Error: {str(e)}"


def test_all_examples(fields: dict) -> List[CodeTestResult]:
    """
    Test all code examples from the form fields.

    Args:
        fields: Dictionary of form fields

    Returns:
        List of CodeTestResult objects
    """
    results = []

    # Test non-compliant examples
    non_compliant = collect_examples(fields, "non_compliant")
    for i, (prose, code) in enumerate(non_compliant, 1):
        if code.strip():
            passed, error = test_rust_code(code)
            results.append(CodeTestResult(
                example_type="non_compliant",
                example_number=i,
                passed=passed,
                error_message=error if not passed else ""
            ))

    # Test compliant examples
    compliant = collect_examples(fields, "compliant")
    for i, (prose, code) in enumerate(compliant, 1):
        if code.strip():
            passed, error = test_rust_code(code)
            results.append(CodeTestResult(
                example_type="compliant",
                example_number=i,
                passed=passed,
                error_message=error if not passed else ""
            ))

    return results


def format_test_results(results: List[CodeTestResult]) -> str:
    """
    Format test results as a markdown section.

    Args:
        results: List of test results

    Returns:
        Formatted markdown string
    """
    if not results:
        return ""

    failed = sum(1 for r in results if not r.passed)
    total = len(results)

    lines = []
    lines.append("### 🧪 Code Example Test Results")
    lines.append("")

    if failed == 0:
        lines.append(f"✅ **All {total} code example(s) compiled successfully!**")
    else:
        lines.append(f"⚠️ **{failed} of {total} code example(s) failed to compile**")
        lines.append("")
        lines.append("| Example | Status | Details |")
        lines.append("|---------|--------|---------|")

        for r in results:
            example_name = rf"{'Non-Compliant' if r.example_type == 'non_compliant' else 'Compliant'} <span>#</span>{r.example_number}"
            if r.passed:
                lines.append(f"| {example_name} | ✅ Pass | - |")
            else:
                # Truncate error for table
                error_preview = r.error_message.split('\n')[0][:80]
                if len(r.error_message) > 80:
                    error_preview += "..."
                lines.append(f"| {example_name} | ❌ Fail | {error_preview} |")

        # Add detailed errors
        failures = [r for r in results if not r.passed]
        if failures:
            lines.append("")
            lines.append("<details>")
            lines.append("<summary><strong>🔍 Click for detailed error messages</strong></summary>")
            lines.append("")

            for r in failures:
                example_name = rf"{'Non-Compliant' if r.example_type == 'non_compliant' else 'Compliant'} Example <span>#</span>{r.example_number}"
                lines.append(f"**{example_name}:**")
                lines.append("```")
                lines.append(r.error_message)
                lines.append("```")
                lines.append("")

            lines.append("</details>")

    lines.append("")
    lines.append("> **Note:** Code examples are tested with `rustc --edition=2021`. ")
    lines.append("> Hidden lines (prefixed with `# `) are included in compilation.")
    lines.append("> Examples without a `fn main()` are automatically wrapped.")

    return "\n".join(lines)


def generate_comment(rst_content: str, chapter: str, test_results: List[CodeTestResult]) -> str:
    """
    Generate a formatted GitHub comment with instructions and RST content.

    Args:
        rst_content: The generated RST content for the guideline
        chapter: The chapter name (e.g., "Concurrency", "Expressions")
        test_results: Results from testing code examples

    Returns:
        Formatted Markdown comment string
    """
    chapter_slug = chapter_to_filename(chapter)
    guideline_id = extract_guideline_id(rst_content)

    # Prepend the SPDX header to the RST content for display
    full_rst_content = GUIDELINE_FILE_HEADER + rst_content.strip()

    # Format test results
    test_results_section = format_test_results(test_results)

    # Determine target path based on whether we have a guideline ID
    if guideline_id:
        target_dir = f"src/coding-guidelines/{chapter_slug}/"
        target_file = f"{target_dir}{guideline_id}.rst.inc"
        chapter_index_file = f"{target_dir}index.rst"
        file_instructions = f"""
### 📁 Target Location

Create a new file: `{target_file}`

> **Note:** The `.rst.inc` extension prevents Sphinx from auto-discovering the file.
> It will be included via the chapter's `index.rst`.

We add it to this path, to allow the newly added guideline to appear in the correct chapter.

### 🗂️ Update Chapter Index

Update `{chapter_index_file}` to include `{guideline_id}.rst.inc`, like so:

```
Chapter Name Here <- chapter heading inside of `{chapter_index_file}`
=================

.. include:: gui_7y0GAMmtMhch.rst.inc -| existing guidelines
.. include:: gui_ADHABsmK9FXz.rst.inc  |
...                                    |
...                                    |
.. include:: gui_RHvQj8BHlz9b.rst.inc  |
.. include:: gui_dCquvqE1csI3.rst.inc -|
.. include:: {guideline_id}.rst.inc <- your new guideline to add
```"""
    else:
        return "No guideline ID generated, failing!"

    comment = f"""## 📋 RST Preview for Coding Guideline

This is an automatically generated preview of your coding guideline in reStructuredText format.
{file_instructions}

{test_results_section}

### 📝 How to Use This

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
{full_rst_content}
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

    # Test code examples
    test_results = test_all_examples(fields)

    # Generate the comment
    comment = generate_comment(rst_content.strip(), chapter, test_results)

    print(comment)


if __name__ == "__main__":
    main()
