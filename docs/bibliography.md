# Bibliography Feature for Safety-Critical Rust Coding Guidelines

This document describes the bibliography feature implementation for the Safety-Critical Rust Coding Guidelines project.

## Overview

The bibliography feature allows guideline authors to include references to external documentation, standards, and other resources that support their guidelines. Citations in the guideline text are clickable links that navigate to the corresponding bibliography entry.

## Features

### 1. In-Text Citations with `:cite:` Role

Contributors can reference citations within guideline text using the `:cite:` role:

```rst
As documented in :cite:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`, union types have specific safety requirements.
```

**Format:** `:cite:`{guideline_id}:{CITATION-KEY}``

- `guideline_id` is the parent guideline's ID (e.g., `gui_Kx9mPq2nL7Yz`)
- `CITATION-KEY` is the citation key in UPPERCASE-WITH-HYPHENS format

The `:cite:` role renders as a clickable `[CITATION-KEY]` link that navigates to the bibliography entry.

### 2. Bibliography Entries with `:bibentry:` Role

Each guideline can include an optional bibliography section with entries defined using the `:bibentry:` role:

```rst
.. guideline:: Union Field Validity
   :id: gui_Kx9mPq2nL7Yz
   ...

   As documented in :cite:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`, unions have requirements.

   .. bibliography::
      :id: bib_Kx9mPq2nL7Yz
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`
           - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html
         * - :bibentry:`gui_Kx9mPq2nL7Yz:CERT-C-INT34`
           - SEI CERT C Coding Standard. "INT34-C." https://wiki.sei.cmu.edu/confluence/x/ItcxBQ
```

**Format:** `:bibentry:`{guideline_id}:{CITATION-KEY}``

The `:bibentry:` role creates an anchor that the `:cite:` role links to, and renders as a bold `[CITATION-KEY]`.

### 3. Why Namespacing?

The guideline ID prefix (`gui_Kx9mPq2nL7Yz:`) is required to avoid conflicts when multiple guidelines use the same citation key (e.g., both guidelines might cite `RUST-REF-UNION`). The prefix ensures each citation anchor is unique across the entire documentation.

When using `generate_guideline_templates.py`, the guideline ID is automatically included in all `:cite:` and `:bibentry:` roles.

### 4. Citation Key Format

Citation keys must follow these rules:
- **Format**: `UPPERCASE-WITH-HYPHENS`
- Must start with an uppercase letter
- Can contain uppercase letters, numbers, and hyphens
- Must end with an uppercase letter or number
- Maximum 50 characters

**Valid examples:**
- `RUST-REF-UNION`
- `CERT-C-INT34`
- `ISO-26262-2018`
- `MISRA-C-2012`

**Invalid examples:**
- `lowercase` - must be uppercase
- `ENDS-WITH-` - cannot end with hyphen
- `-STARTS-HYPHEN` - cannot start with hyphen

### 5. URL Validation

The bibliography validator extension checks:
- URL accessibility (HTTP status)
- URL consistency across guidelines (same URL must use identical citation key and description)
- Citation key format compliance
- Citation references match definitions

**Duplicate URL Consistency:** When the same URL appears in multiple guidelines, all instances must use:
- The same citation key (e.g., all use `RUST-REF-UNION`)
- The same description text (e.g., all use `The Rust Reference. "Unions."`)

This ensures readers see consistent references throughout the documentation.

## Configuration

### conf.py Settings

```python
# Enable URL validation (typically only in CI)
bibliography_check_urls = False  # Set via --validate-urls flag

# Timeout for URL checks in seconds
bibliography_url_timeout = 10

# Whether broken URLs should fail the build
bibliography_fail_on_broken = True

# Whether inconsistent duplicate URLs should fail the build
# (same URL with different citation keys or descriptions)
bibliography_fail_on_inconsistent = True
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

The template generator automatically converts this to the proper `:cite:` and `:bibentry:` role format.

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
├── citation_roles.py           # :cite: and :bibentry: role implementations
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
    ├── bibliography.css        # Bibliography table styling
    └── citation.css            # Citation link styling
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

## Error Messages and Build Failures

All bibliography validation errors will **fail the build**. This ensures that invalid citations and mismatched guideline IDs are caught during development and CI.

The validation runs in two places:
1. **During document parsing**: The `:cite:` and `:bibentry:` roles check format and log errors
2. **During consistency check**: The `bibliography_validator` scans all guidelines and raises `BibliographyValidationError` if any errors are found

All error messages include copy-pasteable fixes to help contributors quickly resolve issues.

### Broken URL
```
WARNING: [bibliography_validator] Broken URL in src/gui_Rm4kWp8sN2Qx.rst:
  URL: https://example.com/broken
  Guideline: gui_Rm4kWp8sN2Qx
  Error: HTTP 404
  Action: Update or remove this reference
```

### Inconsistent Duplicate URL
```
ERROR: Inconsistent bibliography entry for URL:
  URL: https://doc.rust-lang.org/reference/items/unions.html
  Canonical entry (from gui_Kx9mPq2nL7Yz):
    Citation key: [RUST-REF-UNION]
    Description: The Rust Reference. "Unions."
  Guidelines with inconsistent entries: gui_Ht5vBn3mJ9Lw, gui_Qp8xZc4kR6Fy

  Copy-paste fixes:
  In gui_Ht5vBn3mJ9Lw, replace the bibliography entry with:
    * - :bibentry:`gui_Ht5vBn3mJ9Lw:RUST-REF-UNION`
      - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html

  In gui_Qp8xZc4kR6Fy, replace the bibliography entry with:
    * - :bibentry:`gui_Qp8xZc4kR6Fy:RUST-REF-UNION`
      - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html
```

### Invalid Citation Key
```
ERROR: Invalid citation key in :cite: role (coding-guidelines/expressions/gui_Bob7x9KmPq2nL):
  Key: CERT-C-int34
  Must be UPPERCASE-WITH-HYPHENS (e.g., RUST-REF-UNION)
  Copy-paste fix: :cite:`gui_Bob7x9KmPq2nL:CERT-C-INT34`
```

### Invalid Role Format

The error message automatically detects the guideline ID from context and includes it in the suggested fix:

```
ERROR: Invalid :cite: format: "RUST-REF-UNION".
  Expected format: :cite:`gui_XxxYyyZzz:CITATION-KEY`
  Suggested fix: :cite:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`
```

```
ERROR: Invalid :bibentry: format: "[RUST-REF-UNION]".
  Expected format: :bibentry:`gui_XxxYyyZzz:CITATION-KEY`
  Suggested fix: :bibentry:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`
```

### Guideline ID Mismatch

If the guideline ID in a role doesn't match the current guideline:

```
ERROR: Guideline ID mismatch in :cite: role.
  Role uses: gui_Bib7x9KmPq2nL
  Current guideline: gui_Bob7x9KmPq2nL
  Copy-paste fix: :cite:`gui_Bob7x9KmPq2nL:RUST-REF-UNION`
```

```
ERROR: Guideline ID mismatch in :bibentry: role.
  Role uses: gui_Bib7x9KmPq2nL
  Current guideline: gui_Bob7x9KmPq2nL
  Copy-paste fix: :bibentry:`gui_Bob7x9KmPq2nL:RUST-REF-UNION`
```

## Migration

Existing guidelines without bibliographies will continue to work. The bibliography section is optional and will not cause build failures if missing.

### From Plain Text Format

If you have guidelines using the older plain text `[CITATION-KEY]` format, update them to use the role-based syntax:

**Before:**
```rst
As documented in [RUST-REF-UNION], ...

* - **[RUST-REF-UNION]**
  - The Rust Reference...
```

**After:**
```rst
As documented in :cite:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`, ...

* - :bibentry:`gui_Kx9mPq2nL7Yz:RUST-REF-UNION`
  - The Rust Reference...
```
