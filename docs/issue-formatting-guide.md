# Issue Formatting Guide

## Purpose
This guide outlines Markdown standards when submitting a [Coding Guideline issue template](https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/issues/new?template=CODING-GUIDELINE.yml).

We follow these rules to ensure our content converts cleanly from Markdown to reStructuredText (.rst) when an Issue converted to a Pull Request. During that process the [m2r](https://pypi.org/project/m2r/) converter is used, which is then fed into Sphinx for documentation.

---

## Supported formatting (does not break conversion from Issue => Pull Request)
- **Bold** for emphasis or labels (`**Important Note**`).
- *Italics* for a single word or phrase (`*Warning*`).
- `inline code` for identifiers and short tokens (`cargo build`).
- Simple unordered lists:
    - Item 1
    - Item 2
- Simple ordered lists:
    1. First step
    2. Second step


- Tables with basic content:

| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Row 1 Col 1 | Row 1 Col 2 | Row 1 Col 3 |
| Row 2 Col 1 | Row 2 Col 2 | Row 2 Col 3 |

- Links with clear, simple syntax: `[link text](https://example.com)`.
- Simple blockquotes: `> This is a quote.`.

---
## Unsupported formatting (breaks conversion from Issue => Pull Request)

The following types of formatting are not currently supported in the bodies of text submitted. This may change in the future if we find ways to support them.

- **Nested formatting:** Combining different formatting styles, like **bold around `inline code`**, is unreliable.
- **Markdown headings:** Using `#`, `##`, or `###` conflicts with Sphinx's heading structure.
- **Complex lists:** Lists with inconsistent indentation or mixed bullet types often fail.
    - Example:
    ```
    - A list item
      - Another sub-item
       1. A nested list.
    ```
- **Complex tables:** Tables with merged cells, multi-line content, or rich/nested formatting will likely break.
- **Standalone horizontal rules:** Using `---` or `***` will be misinterpreted.
