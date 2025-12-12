#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Migration script to convert existing `.. code-block:: rust` directives
to the new `.. rust-example::` directive format.

This script:
1. Scans RST files for code-block:: rust directives within example contexts
2. Converts them to rust-example:: directives
3. Optionally runs a compilation check to suggest appropriate attributes

Supports both monolithic chapter files (*.rst) and per-guideline files (*.rst.inc).

Usage:
    # Preview changes (dry run)
    uv run python scripts/migrate_rust_examples.py --dry-run

    # Apply changes
    uv run python scripts/migrate_rust_examples.py

    # Apply changes and try to auto-detect which examples need 'ignore'
    uv run python scripts/migrate_rust_examples.py --detect-failures
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add scripts directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from rustdoc_utils import RustExample, compile_single_example

# Pattern to find code-block:: rust within the content
# Use [ \t]* instead of \s* to avoid matching newlines
CODE_BLOCK_PATTERN = re.compile(
    r'^(\s*)\.\.\ code-block::\ rust[ \t]*$',
    re.MULTILINE
)

# Pattern to detect we're inside an example directive
EXAMPLE_DIRECTIVE_PATTERN = re.compile(
    r'^(\s*)\.\.\ (compliant_example|non_compliant_example)::',
    re.MULTILINE
)

# Pattern to match guideline directives
GUIDELINE_PATTERN = re.compile(
    r'^(\s*)\.\.\ guideline::',
    re.MULTILINE
)


def find_rst_files(src_dir: Path) -> List[Path]:
    """
    Find all RST files in the source directory.
    
    Searches for both:
    - *.rst files (chapter index files, monolithic chapter files)
    - *.rst.inc files (per-guideline include files)
    
    Args:
        src_dir: Directory to search
        
    Returns:
        List of Path objects for all RST files found
    """
    rst_files = list(src_dir.glob("**/*.rst"))
    rst_inc_files = list(src_dir.glob("**/*.rst.inc"))
    return rst_files + rst_inc_files


def extract_code_block_content(content: str, start_pos: int, base_indent: str) -> Tuple[str, int]:
    """
    Extract the content of a code block starting at the given position.
    
    Args:
        content: Full file content
        start_pos: Position after the code-block directive line
        base_indent: The indentation of the code-block directive
        
    Returns:
        Tuple of (extracted_code, end_position)
    """
    lines = content[start_pos:].split('\n')
    code_lines = []
    end_pos = start_pos
    in_code = False
    code_indent = None
    # Minimum indent for code content (must be more indented than the directive)
    min_code_indent = len(base_indent) + 4  # At least 4 spaces more than directive
    
    for i, line in enumerate(lines):
        # Track position
        line_len = len(line) + 1  # +1 for newline
        
        # Check if line is empty or whitespace only
        if not line.strip():
            if in_code:
                code_lines.append('')
            end_pos += line_len
            continue
        
        # Check indentation
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        
        # Check if this looks like a new directive (starts with ..)
        if stripped.startswith('.. ') and current_indent <= len(base_indent) + 4:
            # This is a new directive at same or lower level - stop
            break
        
        # Check if this is a directive option (starts with :)
        if stripped.startswith(':') and not in_code:
            # Skip directive options
            end_pos += line_len
            continue
        
        if code_indent is None:
            # First non-empty, non-option line determines code indent
            if current_indent < min_code_indent:
                # Not indented enough - end of code block or empty block
                break
            code_indent = current_indent
            in_code = True
            code_lines.append(stripped)
            end_pos += line_len
        elif current_indent >= code_indent:
            # Still in code block - preserve relative indentation
            relative_indent = ' ' * (current_indent - code_indent)
            code_lines.append(relative_indent + stripped)
            end_pos += line_len
        elif current_indent > len(base_indent):
            # Less indented than code but still more than directive
            # Could be continuation - include it
            relative_indent = ' ' * (current_indent - code_indent) if current_indent >= code_indent else ''
            code_lines.append(relative_indent + stripped)
            end_pos += line_len
        else:
            # Dedented to directive level or less - end of code block
            break
    
    # Clean up trailing empty lines
    while code_lines and not code_lines[-1].strip():
        code_lines.pop()
    
    return '\n'.join(code_lines), end_pos


def find_parent_directive(content: str, pos: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Find the parent directive (compliant_example or non_compliant_example) for a position.
    
    Args:
        content: Full file content
        pos: Position of the code block
        
    Returns:
        Tuple of (directive_type, directive_id) or (None, None)
    """
    # Look backwards from the position for an example directive
    before = content[:pos]
    
    # Find all example directives before this position
    example_matches = list(EXAMPLE_DIRECTIVE_PATTERN.finditer(before))
    
    if not example_matches:
        return None, None
    
    # Get the last (closest) match
    match = example_matches[-1]
    directive_type = match.group(2)
    
    # Try to find the :id: option after this directive
    after_directive = content[match.end():pos]
    id_match = re.search(r':id:\s*(\S+)', after_directive)
    directive_id = id_match.group(1) if id_match else None
    
    return directive_type, directive_id


def find_parent_guideline(content: str, pos: int) -> Optional[str]:
    """
    Find the parent guideline ID for a position.
    
    Args:
        content: Full file content
        pos: Position of the code block
        
    Returns:
        Guideline ID or None
    """
    before = content[:pos]
    
    # Find all guideline directives before this position
    guideline_matches = list(GUIDELINE_PATTERN.finditer(before))
    
    if not guideline_matches:
        return None
    
    # Get the last match
    match = guideline_matches[-1]
    
    # Try to find the :id: option after this directive
    after_directive = content[match.end():pos]
    
    # Only look until the next directive (any directive)
    next_directive = re.search(r'\n\s*\.\. \w+::', after_directive)
    if next_directive:
        after_directive = after_directive[:next_directive.start()]
    
    id_match = re.search(r':id:\s*(\S+)', after_directive)
    return id_match.group(1) if id_match else None


def convert_code_block_to_rust_example(
    content: str,
    detect_failures: bool = False,
    prelude: str = ""
) -> Tuple[str, List[Dict]]:
    """
    Convert all code-block:: rust directives to rust-example:: directives.
    
    This does a simple in-place replacement of the directive line only,
    leaving the code content exactly as-is.
    
    Args:
        content: The RST file content
        detect_failures: Whether to try compiling and add :ignore: for failures
        prelude: Optional prelude code
        
    Returns:
        Tuple of (converted_content, list of changes made)
    """
    changes = []
    
    # Find all matches first
    matches = list(CODE_BLOCK_PATTERN.finditer(content))
    
    # Filter to only those inside example directives
    valid_matches = []
    for match in matches:
        parent_type, parent_id = find_parent_directive(content, match.start())
        if parent_type:
            guideline_id = find_parent_guideline(content, match.start())
            valid_matches.append((match, parent_type, parent_id, guideline_id))
    
    # Process in reverse order so positions don't shift
    result = content
    for match, parent_type, parent_id, guideline_id in reversed(valid_matches):
        indent = match.group(1)
        start = match.start()
        end = match.end()
        
        # For detect_failures mode, we need to extract the code
        attr = None
        attr_value = None
        code_preview = ""
        
        if detect_failures:
            code, _ = extract_code_block_content(content, end, indent)
            code_preview = code[:100] + '...' if len(code) > 100 else code
            
            if code.strip():
                example = RustExample(
                    source_file="migration",
                    line_number=0,
                    code=code,
                    display_code=code,
                    parent_directive=parent_type,
                    parent_id=parent_id or "",
                    guideline_id=guideline_id or "",
                )
                
                result_check = compile_single_example(example, prelude)
                if not result_check.passed:
                    attr = 'ignore'
        
        # Build the replacement
        new_directive = f"{indent}.. rust-example::"
        
        if attr:
            new_directive += f"\n{indent}    :{attr}:"
            if attr_value:
                new_directive += f" {attr_value}"
        
        # Replace just the matched portion
        result = result[:start] + new_directive + result[end:]
        
        # Record the change
        changes.append({
            'parent_type': parent_type,
            'parent_id': parent_id,
            'guideline_id': guideline_id,
            'attr': attr,
            'code_preview': code_preview,
        })
    
    # Reverse changes list so it's in document order
    changes.reverse()
    
    return result, changes


def process_file(
    file_path: Path,
    dry_run: bool = True,
    detect_failures: bool = False,
    prelude: str = "",
    verbose: bool = False
) -> List[Dict]:
    """
    Process a single RST file.
    
    Args:
        file_path: Path to the RST file (supports .rst and .rst.inc)
        dry_run: If True, don't write changes
        detect_failures: Whether to detect compilation failures
        prelude: Optional prelude code
        verbose: Print detailed information
        
    Returns:
        List of changes made
    """
    content = file_path.read_text()
    
    new_content, changes = convert_code_block_to_rust_example(
        content,
        detect_failures=detect_failures,
        prelude=prelude
    )
    
    if changes:
        if verbose:
            print(f"\n📄 {file_path}")
            for change in changes:
                attr_info = f" [{change['attr']}]" if change['attr'] else ""
                print(f"   ✏️  {change['parent_type']} ({change['parent_id']}){attr_info}")
        
        if not dry_run:
            file_path.write_text(new_content)
            if verbose:
                print("   ✅ Written")
    
    return changes


def main():
    parser = argparse.ArgumentParser(
        description="Migrate code-block:: rust to rust-example:: directives"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing"
    )
    parser.add_argument(
        "--detect-failures",
        action="store_true",
        help="Try compiling examples and add :ignore: for failures"
    )
    parser.add_argument(
        "--prelude",
        type=str,
        default=None,
        help="Path to prelude file for compilation checks"
    )
    parser.add_argument(
        "--src-dir",
        type=str,
        default="src/coding-guidelines",
        help="Source directory to scan"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    args = parser.parse_args()
    
    src_dir = Path(args.src_dir)
    if not src_dir.exists():
        print(f"❌ Source directory not found: {src_dir}")
        sys.exit(1)
    
    # Load prelude if specified
    prelude = ""
    if args.prelude:
        prelude_path = Path(args.prelude)
        if prelude_path.exists():
            prelude = prelude_path.read_text()
        else:
            print(f"⚠️  Prelude file not found: {prelude_path}")
    
    # Find and process RST files (both .rst and .rst.inc)
    all_files = find_rst_files(src_dir)
    print(f"🔍 Found {len(all_files)} RST files in {src_dir}")
    
    if args.dry_run:
        print("📋 DRY RUN - no files will be modified")
    
    total_changes = 0
    files_changed = 0
    
    for file_path in all_files:
        changes = process_file(
            file_path,
            dry_run=args.dry_run,
            detect_failures=args.detect_failures,
            prelude=prelude,
            verbose=args.verbose
        )
        
        if changes:
            total_changes += len(changes)
            files_changed += 1
    
    print(f"\n{'='*60}")
    print(f"Summary: {total_changes} code blocks in {files_changed} files")
    
    if args.dry_run and total_changes > 0:
        print("\nRun without --dry-run to apply changes")


if __name__ == "__main__":
    main()
