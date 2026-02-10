# Scripts

This directory contains utility scripts for managing coding guidelines.

## Scripts Overview

| Script | Purpose |
|--------|---------|
| `guideline-from-issue.py` | Transforms issue JSON to RST format for guidelines |
| `generate-rst-comment.py` | Generates GitHub comment with RST preview |
| `guideline_utils.py` | Shared utility functions for guideline processing |
| `rustdoc_utils.py` | Shared utilities for Rust example handling |
| `migrate_rust_examples.py` | Migrate code-block to rust-example directives |
| `extract_rust_examples.py` | Extract and test Rust examples |

---

## Bibliography and Citations

The coding guidelines support bibliography references using standard Markdown reference link syntax.

### In the Issue Template

When creating a new guideline via the issue template:

1. **Add bibliography entries** in the Bibliography field using Markdown reference links:
   ```
   [RUST-REF-UNION]: https://doc.rust-lang.org/reference/items/unions.html "The Rust Reference | Unions"
   [CERT-C-INT34]: https://wiki.sei.cmu.edu/confluence/x/ItcxBQ "SEI CERT C | INT34-C. Do not shift by negative bits"
   ```

2. **Reference citations** in your Amplification, Rationale, or example prose using `[CITATION-KEY]`:
   ```markdown
   As documented in [RUST-REF-UNION], union types in Rust have specific safety requirements.
   The CERT C Coding Standard [CERT-C-INT34] provides guidance on avoiding undefined behavior.
   ```

### Bibliography Entry Format

Use standard Markdown reference link syntax with "Author | Title" in the title string:

```
[KEY]: URL "Author | Title"
```

The author and title are separated by a pipe (`|`).

### Citation Key Rules

- Must be **UPPERCASE-WITH-HYPHENS** (e.g., `RUST-REF-UNION`, `CERT-C-INT34`)
- Start with a letter
- Contain only letters, numbers, and hyphens
- Maximum 50 characters

### How It Works

1. The `generate-rst-comment.py` script:
   - Parses bibliography entries from the issue
   - Validates citation key formats and URL formats
   - Checks that all `[CITATION-KEY]` references have matching entries
   - Warns about unused bibliography entries

2. The `guideline_utils.py` script:
   - Converts Markdown `[CITATION-KEY]` to RST `:cite:\`gui_xxx:CITATION-KEY\`` roles
   - Generates bibliography blocks with `:bibentry:` anchors
   - Namespaces citations per-guideline to avoid conflicts

3. The generated RST:
   - Uses `:cite:` roles for clickable in-text citations
   - Uses `:bibentry:` roles for bibliography anchors with back-links
   - Supports navigation between citations and their definitions

### Example

**Input (Markdown in issue):**
```markdown
### Amplification
As documented in [RUST-REF-UNION], unions have specific requirements.

### Bibliography
[RUST-REF-UNION]: https://doc.rust-lang.org/reference/items/unions.html "The Rust Reference | Unions"
```

**Output (RST):**
```rst
.. guideline:: Example Guideline
   :id: gui_abc123XyzQrs
   
   As documented in :cite:`gui_abc123XyzQrs:RUST-REF-UNION`, unions have specific requirements.
   
   .. bibliography::
      :id: bib_abc123XyzQrs
      :status: draft
      
      .. list-table::
         :header-rows: 0
         
         * - :bibentry:`gui_abc123XyzQrs:RUST-REF-UNION`
           - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html
```

---

## Rust Example Scripts

These scripts support the rustdoc-style code example system.

### `rustdoc_utils.py`

A shared module containing common functions for Rust example handling:

- `RustExample` - Data class representing a Rust code example
- `TestResult` - Data class for test results
- `process_hidden_lines()` - Handle rustdoc hidden line syntax (`# `)
- `generate_doctest()` - Generate rustdoc-style doctest from example
- `generate_test_crate()` - Generate a Cargo crate for testing
- `compile_single_example()` - Compile and test a single example
- `format_test_results()` - Format results for display

### `migrate_rust_examples.py`

Converts existing `.. code-block:: rust` directives to the new `.. rust-example::` directive format.

```bash
# Preview changes (dry run)
uv run python scripts/migrate_rust_examples.py --dry-run

# Apply changes
uv run python scripts/migrate_rust_examples.py

# Apply changes and try to auto-detect which examples need 'ignore'
uv run python scripts/migrate_rust_examples.py --detect-failures
```

**Options:**
- `--dry-run`: Preview changes without writing
- `--detect-failures`: Try compiling examples and add `:ignore:` for failures
- `--prelude PATH`: Path to prelude file for compilation checks
- `--src-dir DIR`: Source directory to scan (default: `src/coding-guidelines`)
- `-v, --verbose`: Verbose output

### `extract_rust_examples.py`

Extracts Rust examples from RST documentation and tests them.

```bash
# Extract examples and generate test crate
uv run python scripts/extract_rust_examples.py --extract

# Extract and test examples
uv run python scripts/extract_rust_examples.py --test

# Just test (assuming already extracted)
uv run python scripts/extract_rust_examples.py --test-only

# Output results as JSON
uv run python scripts/extract_rust_examples.py --test --json results.json

# List all examples
uv run python scripts/extract_rust_examples.py --list
```

**Options:**
- `--extract`: Extract examples and generate test crate
- `--test`: Extract and test examples
- `--test-only`: Test already extracted examples
- `--list`: Just list all examples found
- `--src-dir DIR`: Source directory to scan (default: `src/coding-guidelines`)
- `--output-dir DIR`: Output directory for generated crate (default: `build/examples`)
- `--prelude PATH`: Path to shared prelude file
- `--json PATH`: Output results to JSON file
- `--fail-on-error`: Exit with error code if any tests fail
- `-v, --verbose`: Verbose output

---

## The `rust-example` Directive

The `.. rust-example::` directive is a custom Sphinx directive for Rust code examples with rustdoc-style attributes.

### Basic Usage

```rst
.. rust-example::

    fn example() {
        println!("Hello, world!");
    }
```

### Rustdoc Attributes

**`:ignore:`** - Don't compile this example:
```rst
.. rust-example::
    :ignore:

    fn incomplete_example() {
        // This code is intentionally incomplete
    }
```

**`:compile_fail:`** - Example should fail to compile:
```rst
.. rust-example::
    :compile_fail: E0277

    fn type_error() {
        let x: i32 = "string";  // Type mismatch
    }
```

**`:should_panic:`** - Example should panic at runtime:
```rst
.. rust-example::
    :should_panic:

    fn panicking() {
        panic!("This should panic");
    }
```

**`:no_run:`** - Compile but don't execute:
```rst
.. rust-example::
    :no_run:

    fn infinite_loop() {
        loop {}
    }
```

### Hidden Lines

Use `# ` prefix for lines that should compile but not display:

```rst
.. rust-example::

    # use std::collections::HashMap;
    # fn main() {
    let map = HashMap::new();
    # }
```

To show hidden lines in rendered output, add `:show_hidden:`:

```rst
.. rust-example::
    :show_hidden:

    # use std::collections::HashMap;
    let map = HashMap::new();
```

### Rendering

In the rendered documentation, examples with attributes show a badge:

- **ignore** (gray): ⏭ ignore
- **compile_fail** (red): ✗ compile_fail(E0277)
- **should_panic** (orange): 💥 should_panic
- **no_run** (blue): ⚙ no_run

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
- `extract_citation_references()` - Extract `[CITATION-KEY]` patterns from text
- `convert_citations_to_rst()` - Convert Markdown citations to `:cite:` roles
- `validate_citation_references()` - Check that citations match bibliography

---

## `guideline-from-issue.py`

This script transforms a GitHub issue's JSON data into reStructuredText format for coding guidelines.

### Usage

```bash
# From a local JSON file
cat path/to/issue.json | uv run python scripts/guideline-from-issue.py

# From GitHub API directly
curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/123 | uv run python scripts/guideline-from-issue.py

# Save the output to the appropriate chapter file
cat path/to/issue.json | uv run python scripts/guideline-from-issue.py --save
```

### Options

- `--save`: Save the generated RST content to the appropriate chapter file in `src/coding-guidelines/`

---

## `generate-rst-comment.py`

This script generates a formatted GitHub comment containing an RST preview of a coding guideline.

### Usage

```bash
# From a local JSON file
cat path/to/issue.json | uv run python scripts/generate-rst-comment.py

# From GitHub API directly
curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/123 | uv run python scripts/generate-rst-comment.py
```

### Features

- **Code Compilation Testing**: Tests all Rust code examples and reports compilation errors
- **Bibliography Validation**: Validates citation key format, URL format, and cross-references
- **Citation Reference Checking**: Ensures all `[CITATION-KEY]` references have matching bibliography entries
- **Unused Entry Detection**: Warns about bibliography entries that aren't referenced

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
