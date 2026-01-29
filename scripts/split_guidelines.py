#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Migration script to split monolithic chapter RST files into per-guideline files.

This script:
1. Parses existing chapter files (e.g., expressions.rst)
2. Extracts each guideline with its nested content (rationale, examples)
3. Creates a subdirectory per chapter (e.g., expressions/)
4. Writes each guideline to its own file (e.g., expressions/gui_xxx.rst)
5. Generates a chapter index.rst that includes all guidelines

Design decisions for future Option 2 migration:
- Each guideline file is self-contained (has its own default-domain, SPDX header)
- Files are named by guideline ID for stable URLs
- Alphabetical ordering enables predictable merge conflict resolution
- Chapter index only contains includes, no guideline content

Usage:
    # Dry run - see what would happen
    uv run python scripts/split_guidelines.py --dry-run

    # Process a single chapter
    uv run python scripts/split_guidelines.py --chapter expressions

    # Process all chapters
    uv run python scripts/split_guidelines.py --all

    # Specify custom source directory
    uv run python scripts/split_guidelines.py --all --src-dir src/coding-guidelines
"""

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

# SPDX header to prepend to each generated file
SPDX_HEADER = """\
.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

"""

# Pattern to match guideline directive start
GUIDELINE_PATTERN = re.compile(
    r'^(\.\. guideline::)\s*(.*?)$',
    re.MULTILINE
)

# Pattern to extract guideline ID from :id: option
ID_PATTERN = re.compile(r':id:\s*(gui_[A-Za-z0-9_]+)')


def find_guideline_boundaries(content: str) -> List[Tuple[int, int, str]]:
    """
    Find the start and end positions of each guideline in the content.
    
    Returns:
        List of (start_pos, end_pos, guideline_id) tuples
    """
    boundaries = []
    matches = list(GUIDELINE_PATTERN.finditer(content))
    
    for i, match in enumerate(matches):
        start = match.start()
        
        # End is either the start of the next guideline or end of file
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(content)
        
        # Extract the guideline content to find the ID
        guideline_content = content[start:end]
        id_match = ID_PATTERN.search(guideline_content)
        
        if id_match:
            guideline_id = id_match.group(1)
        else:
            # Fallback: generate ID from position
            guideline_id = f"gui_unknown_{i}"
            print(f"  Warning: Could not find ID for guideline at position {start}", file=sys.stderr)
        
        boundaries.append((start, end, guideline_id))
    
    return boundaries


def extract_chapter_header(content: str, first_guideline_start: int) -> str:
    """
    Extract any content before the first guideline (chapter title, intro text).
    
    Returns:
        The header content, stripped of SPDX and default-domain (we'll add fresh ones)
    """
    header = content[:first_guideline_start]
    
    # Remove existing SPDX header
    header = re.sub(r'\.\. SPDX-License-Identifier:.*?\n', '', header)
    header = re.sub(r'\s*SPDX-FileCopyrightText:.*?\n', '', header)
    
    # Remove existing default-domain
    header = re.sub(r'\.\. default-domain::.*?\n\n?', '', header)
    
    return header.strip()


def extract_guideline_content(content: str, start: int, end: int) -> str:
    """
    Extract a single guideline's content.
    
    Returns:
        The guideline content, ready to be written to its own file
    """
    guideline = content[start:end].rstrip()
    return guideline


def generate_chapter_index(chapter_name: str, chapter_title: str, guideline_ids: List[str], header_content: str = "") -> str:
    """
    Generate the chapter index.rst content with includes.
    
    Args:
        chapter_name: Directory name (e.g., "expressions")
        chapter_title: Display title (e.g., "Expressions")
        guideline_ids: List of guideline IDs, will be sorted alphabetically
        header_content: Optional introductory content after the title
    """
    # Sort IDs alphabetically for predictable ordering
    sorted_ids = sorted(guideline_ids)
    
    lines = [
        ".. SPDX-License-Identifier: MIT OR Apache-2.0",
        "   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors",
        "",
        ".. default-domain:: coding-guidelines",
        "",
        chapter_title,
        "=" * len(chapter_title),
        "",
    ]
    
    if header_content:
        lines.append(header_content)
        lines.append("")
    
    # Add includes for each guideline (using .rst.inc extension)
    for gid in sorted_ids:
        lines.append(f".. include:: {gid}.rst.inc")
    
    lines.append("")  # Trailing newline
    
    return "\n".join(lines)


def parse_chapter_file(filepath: Path) -> Tuple[str, str, List[Tuple[str, str]]]:
    """
    Parse a chapter file and extract its components.
    
    Returns:
        Tuple of (chapter_title, header_content, [(guideline_id, guideline_content), ...])
        For empty chapters, returns (title, header, []) with an empty guidelines list.
    """
    content = filepath.read_text()
    
    # Find all guidelines
    boundaries = find_guideline_boundaries(content)
    
    if not boundaries:
        # Empty chapter - extract title from content
        title_match = re.search(r'^([^\n]+)\n=+', content)
        if title_match:
            chapter_title = title_match.group(1).strip()
        else:
            chapter_title = filepath.stem.replace("-", " ").title()
        return chapter_title, "", []
    
    # Extract header (everything before first guideline)
    header = extract_chapter_header(content, boundaries[0][0])
    
    # Extract chapter title from header
    title_match = re.search(r'^([^\n]+)\n=+', header)
    if title_match:
        chapter_title = title_match.group(1).strip()
        # Remove title from header content
        header = header[title_match.end():].strip()
    else:
        chapter_title = filepath.stem.replace("-", " ").title()
    
    # Extract each guideline
    guidelines = []
    for start, end, gid in boundaries:
        guideline_content = extract_guideline_content(content, start, end)
        guidelines.append((gid, guideline_content))
    
    return chapter_title, header, guidelines


def split_chapter(
    src_file: Path,
    output_dir: Path,
    dry_run: bool = False,
    verbose: bool = False
) -> Tuple[int, List[str]]:
    """
    Split a chapter file into per-guideline files.
    
    Args:
        src_file: Path to the source chapter file (e.g., expressions.rst)
        output_dir: Base output directory (e.g., src/coding-guidelines)
        dry_run: If True, don't write files
        verbose: If True, print detailed progress
    
    Returns:
        Tuple of (number of guidelines, list of guideline IDs)
    """
    chapter_name = src_file.stem
    chapter_dir = output_dir / chapter_name
    
    print(f"\nProcessing {src_file.name}...")
    
    # Parse the chapter
    chapter_title, header_content, guidelines = parse_chapter_file(src_file)
    
    if not guidelines:
        print("  No guidelines found - creating empty chapter structure")
    else:
        print(f"  Found {len(guidelines)} guidelines")
    
    print(f"  Chapter title: {chapter_title}")
    
    if verbose:
        for gid, _ in guidelines:
            print(f"    - {gid}")
    
    if dry_run:
        print(f"  Would create directory: {chapter_dir}")
        print(f"  Would create {len(guidelines)} guideline files (.rst.inc)")
        print("  Would create index.rst")
        return len(guidelines), [g[0] for g in guidelines]
    
    # Create chapter directory
    chapter_dir.mkdir(parents=True, exist_ok=True)
    
    # Write each guideline file (using .rst.inc extension to prevent Sphinx auto-discovery)
    guideline_ids = []
    for gid, content in guidelines:
        guideline_file = chapter_dir / f"{gid}.rst.inc"
        full_content = SPDX_HEADER + content + "\n"
        guideline_file.write_text(full_content)
        guideline_ids.append(gid)
        
        if verbose:
            print(f"  Created {guideline_file.name}")
    
    # Generate and write index
    index_content = generate_chapter_index(
        chapter_name,
        chapter_title,
        guideline_ids,
        header_content
    )
    index_file = chapter_dir / "index.rst"
    index_file.write_text(index_content)
    print(f"  Created {index_file}")
    
    return len(guidelines), guideline_ids


def update_main_index(
    index_file: Path,
    chapter_names: List[str],
    dry_run: bool = False
):
    """
    Update the main coding-guidelines/index.rst to point to chapter subdirectories.
    
    This changes entries like 'expressions' to 'expressions/index'.
    """
    if not index_file.exists():
        print(f"Warning: Main index not found at {index_file}", file=sys.stderr)
        return
    
    content = index_file.read_text()
    original = content
    
    updated_chapters = []
    for chapter in chapter_names:
        # Replace 'chapter' with 'chapter/index' in toctree
        # Match the chapter name at the end of a line (with optional trailing whitespace)
        # but only if it's not already followed by /index
        pattern = rf'(^[ \t]+){re.escape(chapter)}([ \t]*$)'
        
        # Check if this chapter is in the content and not already updated
        if re.search(pattern, content, re.MULTILINE):
            replacement = rf'\g<1>{chapter}/index\g<2>'
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            updated_chapters.append(chapter)
    
    if content != original:
        if dry_run:
            print(f"\nWould update main index at {index_file}")
            print(f"  Chapters to update: {', '.join(updated_chapters)}")
        else:
            index_file.write_text(content)
            print(f"\nUpdated main index at {index_file}")
            print(f"  Updated chapters: {', '.join(updated_chapters)}")
    else:
        print("\nMain index already up to date (or no matching chapters found)")


def get_chapter_files(src_dir: Path) -> List[Path]:
    """
    Get list of chapter RST files (excluding index.rst and non-guideline files).
    """
    # These are known chapter files based on index.rst toctree
    known_chapters = [
        "types-and-traits",
        "patterns",
        "expressions",
        "values",
        "statements",
        "functions",
        "associated-items",
        "implementations",
        "generics",
        "attributes",
        "entities-and-resolution",
        "ownership-and-destruction",
        "exceptions-and-errors",
        "concurrency",
        "program-structure-and-compilation",
        "unsafety",
        "macros",
        "ffi",
        "inline-assembly",
    ]
    
    chapter_files = []
    for name in known_chapters:
        filepath = src_dir / f"{name}.rst"
        if filepath.exists():
            chapter_files.append(filepath)
    
    return chapter_files


def main():
    parser = argparse.ArgumentParser(
        description="Split chapter RST files into per-guideline files"
    )
    
    parser.add_argument(
        "--chapter",
        type=str,
        help="Process a single chapter (e.g., 'expressions')"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all chapter files"
    )
    parser.add_argument(
        "--src-dir",
        type=str,
        default="src/coding-guidelines",
        help="Source directory containing chapter files"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making changes"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--update-index",
        action="store_true",
        help="Update main index.rst to point to chapter subdirectories"
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove old chapter files after successful migration (use with caution!)"
    )
    
    args = parser.parse_args()
    
    if not args.chapter and not args.all:
        parser.print_help()
        print("\nError: Specify --chapter or --all", file=sys.stderr)
        sys.exit(1)
    
    src_dir = Path(args.src_dir)
    if not src_dir.exists():
        print(f"Error: Source directory not found: {src_dir}", file=sys.stderr)
        sys.exit(1)
    
    if args.dry_run:
        print("=== DRY RUN - No files will be modified ===\n")
    
    # Determine which files to process
    if args.chapter:
        chapter_file = src_dir / f"{args.chapter}.rst"
        if not chapter_file.exists():
            print(f"Error: Chapter file not found: {chapter_file}", file=sys.stderr)
            sys.exit(1)
        files_to_process = [chapter_file]
    else:
        files_to_process = get_chapter_files(src_dir)
    
    print(f"Found {len(files_to_process)} chapter file(s) to process")
    
    # Process each file
    total_guidelines = 0
    processed_chapters = []
    empty_chapters = []
    
    for filepath in files_to_process:
        try:
            count, _ = split_chapter(
                filepath,
                src_dir,
                dry_run=args.dry_run,
                verbose=args.verbose
            )
            total_guidelines += count
            processed_chapters.append(filepath.stem)
            if count == 0:
                empty_chapters.append(filepath.stem)
        except Exception as e:
            print(f"Error processing {filepath}: {e}", file=sys.stderr)
            if args.verbose:
                import traceback
                traceback.print_exc()
    
    print(f"\n{'Would process' if args.dry_run else 'Processed'} {total_guidelines} guidelines across {len(processed_chapters)} chapters")
    if empty_chapters:
        print(f"  ({len(empty_chapters)} chapters have no guidelines yet: {', '.join(empty_chapters)})")
    
    # Optionally update main index
    if args.update_index and processed_chapters:
        main_index = src_dir / "index.rst"
        update_main_index(main_index, processed_chapters, dry_run=args.dry_run)
    
    # Optionally cleanup old files
    if args.cleanup and processed_chapters and not args.dry_run:
        print("\n=== Cleaning up old chapter files ===")
        for chapter in processed_chapters:
            old_file = src_dir / f"{chapter}.rst"
            if old_file.exists():
                old_file.unlink()
                print(f"  Removed {old_file}")
    elif args.cleanup and args.dry_run:
        print("\n=== Would remove these old chapter files ===")
        for chapter in processed_chapters:
            old_file = src_dir / f"{chapter}.rst"
            if old_file.exists():
                print(f"  Would remove {old_file}")
    
    # Print next steps
    if not args.dry_run:
        print("\n=== Next Steps ===")
        if not args.update_index:
            print("1. Run again with --update-index to update the main toctree")
        if not args.cleanup:
            print("2. Remove old chapter files manually, or run again with --cleanup:")
            for chapter in processed_chapters:
                old_file = src_dir / f"{chapter}.rst"
                if old_file.exists():
                    print(f"     rm {old_file}")
        print("3. Build the documentation to verify: ./make.py")
        print("4. Update any tooling (guideline-from-issue.py, etc.)")
    else:
        print("\n=== To apply changes ===")
        print("Run without --dry-run:")
        print("  uv run python scripts/split_guidelines.py --all --update-index --cleanup")


if __name__ == "__main__":
    main()
