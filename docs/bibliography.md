# Bibliography Feature for Safety-Critical Rust Coding Guidelines

This document describes the bibliography feature implementation for the Safety-Critical Rust Coding Guidelines project.

## Overview

The bibliography feature allows guideline authors to include references to external documentation, standards, and other resources that support their guidelines.

## Features

### 1. In-Text Citations
Contributors can reference citations within guideline text using the `[CITATION-KEY]` syntax:

```rst
As documented in [RUST-REF-UNION], union types have specific safety requirements.
```

### 2. Bibliography Section
Each guideline can include an optional bibliography section. The ID is auto-generated using the format `bib_` followed by 12 random alphanumeric characters:

```rst
.. bibliography::
   :id: bib_7y0GAMmtMhch
   :status: draft

   .. list-table::
      :header-rows: 0
      :widths: auto
      :class: bibliography-table

      * - .. [RUST-REF-UNION]
        - | The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html
      * - .. [CERT-C-INT34]
        - | SEI CERT C Coding Standard. "INT34-C." https://wiki.sei.cmu.edu/confluence/x/ItcxBQ
```

**Note:** When using `generate_guideline_templates.py`, the bibliography ID is automatically generated. The format follows the same pattern as other sphinx-needs IDs (e.g., `gui_`, `rat_`, `compl_ex_`, `non_compl_ex_`).

### 3. Citation Key Format
Citation keys must follow these rules:
- **Format**: `[UPPERCASE-WITH-HYPHENS]`
- Must start with an uppercase letter
- Can contain uppercase letters, numbers, and hyphens
- Must end with an uppercase letter or number
- Maximum 50 characters

**Valid examples:**
- `[RUST-REF-UNION]`
- `[CERT-C-INT34]`
- `[ISO-26262-2018]`
- `[MISRA-C-2012]`

**Invalid examples:**
- `[lowercase]` - must be uppercase
- `[ENDS-WITH-]` - cannot end with hyphen
- `[-STARTS-HYPHEN]` - cannot start with hyphen

### 4. URL Validation
The bibliography validator extension checks:
- URL accessibility (HTTP status)
- Duplicate URLs across guidelines
- Citation key format compliance
- Citation references match definitions

## Configuration

### conf.py Settings

```python
# Enable URL validation (typically only in CI)
bibliography_check_urls = False  # Set via --validate-urls flag

# Timeout for URL checks in seconds
bibliography_url_timeout = 10

# Whether broken URLs should fail the build
bibliography_fail_on_broken = True

# Whether duplicate URLs should fail the build
bibliography_fail_on_duplicates = True
```

### Build Commands

```bash
# Normal build (no URL validation)
./make.py

# Build with URL validation (for CI)
./make.py --validate-urls

# Debug build with URL validation
./make.py --debug --validate-urls
```

## GitHub Issue Template

The coding guideline issue template includes an optional bibliography field:

```yaml
- type: textarea
  id: bibliography
  attributes:
    label: Bibliography
    description: |
      Optional list of references. Format:
      [CITATION-KEY] Author. "Title." URL
```

**Example input:**
```
[RUST-REF-UNION] The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html
[CERT-C-INT34] SEI CERT C Coding Standard. "INT34-C. Do not shift an expression by a negative number of bits." https://wiki.sei.cmu.edu/confluence/x/ItcxBQ
```

## CI Integration

### Pull Requests to Main
- Bibliography URLs are validated on every PR to main
- Broken or duplicate URLs will fail the build

### Nightly Builds
- Full URL validation runs nightly
- Creates GitHub issues automatically if validation fails

## File Structure

```
exts/coding_guidelines/
├── bibliography_validator.py   # URL and citation validation
├── __init__.py                 # Extension setup (updated)
└── write_guidelines_ids.py     # JSON export (updated)

scripts/
├── guideline_utils.py          # Bibliography parsing utilities
└── generate-rst-comment.py     # Preview generation (updated)

.github/
├── ISSUE_TEMPLATE/
│   └── CODING-GUIDELINE.yml    # Issue template with bibliography field
└── workflows/
    ├── build-guidelines.yml    # Build workflow with URL validation
    └── nightly.yml             # Nightly validation

src/
├── conf.py                     # Sphinx config with bibliography settings
└── _static/
    └── bibliography.css        # Bibliography styling
```

## JSON Export Format

The `guidelines-ids.json` now includes bibliography data. All IDs follow the same format: `{prefix}_{12_random_alphanumeric_chars}`:

```json
{
  "documents": [
    {
      "guidelines": [
        {
          "id": "gui_7y0GAMmtMhch",
          "title": "Union Field Validity",
          "rationale": { "id": "rat_ADHABsmK9FXz", "checksum": "..." },
          "non_compliant_example": { "id": "non_compl_ex_RHvQj8BHlz9b", "checksum": "..." },
          "compliant_example": { "id": "compl_ex_dCquvqE1csI3", "checksum": "..." },
          "bibliography": { "id": "bib_Xn3pQr7sT2vW", "checksum": "..." }
        }
      ]
    }
  ]
}
```

## Error Messages

### Broken URL
```
WARNING: [bibliography_validator] Broken URL in src/gui_Foo.rst:
  URL: https://example.com/broken
  Guideline: gui_Foo
  Error: HTTP 404
  Action: Update or remove this reference
```

### Duplicate URL
```
WARNING: [bibliography_validator] Duplicate URL detected:
  URL: https://doc.rust-lang.org/reference/items/unions.html
  Found in: gui_UnionFieldValidity, gui_UnionLayout
  Action: Consider if both guidelines need this reference
```

### Invalid Citation Key
```
ERROR: Invalid citation key format: 'lowercase-key'. 
Expected: [UPPERCASE-WITH-HYPHENS] (e.g., [RUST-REF-UNION], [CERT-C-INT34])
```

## Migration

Existing guidelines without bibliographies will continue to work. The bibliography section is optional and will not cause build failures if missing.
