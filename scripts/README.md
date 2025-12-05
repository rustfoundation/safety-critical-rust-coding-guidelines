# Scripts

This directory contains utility scripts for managing coding guidelines.

**Location: scripts/README.md (replaces existing file)**

## Scripts Overview

| Script | Purpose |
|--------|---------|
| `auto-pr-helper.py` | Transforms issue JSON to RST format (used by auto-PR workflow) |
| `generate-rst-comment.py` | Generates GitHub comment with RST preview |
| `guideline_utils.py` | Shared utility functions for guideline processing |

---

## `guideline_utils.py`

A shared module containing common functions used by other scripts:

- `md_to_rst()` - Convert Markdown to reStructuredText using Pandoc
- `normalize_md()` - Fix Markdown formatting issues
- `normalize_list_separation()` - Ensure proper list formatting for Pandoc
- `extract_form_fields()` - Parse issue body into field dictionary
- `guideline_template()` - Generate RST from fields dictionary
- `chapter_to_filename()` - Convert chapter name to filename slug
- `save_guideline_file()` - Append guideline to chapter file

---

## `auto-pr-helper.py`

This script transforms a GitHub issue's JSON data into reStructuredText format for coding guidelines.

### Usage

```bash
# From a local JSON file
cat path/to/issue.json | uv run python scripts/auto-pr-helper.py

# From GitHub API directly
curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/123 | uv run python scripts/auto-pr-helper.py

# Save the output to the appropriate chapter file
cat path/to/issue.json | uv run python scripts/auto-pr-helper.py --save
```

### Options

- `--save`: Save the generated RST content to the appropriate chapter file in `src/coding-guidelines/`

---

## `generate-rst-comment.py`

This script generates a formatted GitHub comment containing an RST preview of a coding guideline. It's used by the RST Preview Comment workflow to post helpful comments on coding guideline issues.

### Usage

```bash
# From a local JSON file
cat path/to/issue.json | uv run python scripts/generate-rst-comment.py

# From GitHub API directly
curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/123 | uv run python scripts/generate-rst-comment.py
```

### Output

The script outputs a Markdown-formatted comment that includes:

1. **Instructions** on how to use the RST content
2. **Target file path** indicating which chapter file to add the guideline to
3. **Collapsible RST content** that can be copied and pasted

### Example Output

```markdown
## 📋 RST Preview for Coding Guideline

This is an automatically generated preview...

### 📁 Target File
Add this guideline to: `src/coding-guidelines/concurrency.rst`

### 📝 How to Use This
1. Fork the repository...
...

<details>
<summary>📄 Click to expand RST content</summary>

\`\`\`rst
.. guideline:: My Guideline Title
    :id: gui_ABC123...
\`\`\`

</details>
```

---

## How to Get Issue JSON from GitHub API

To work with these scripts locally, you can fetch issue data from the GitHub API:

```bash
curl https://api.github.com/repos/OWNER/REPO/issues/ISSUE_NUMBER > issue.json
```

For example:

```bash
curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/156 > issue.json
```
