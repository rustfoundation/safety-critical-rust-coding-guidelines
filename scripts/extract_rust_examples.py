#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Extract and test Rust examples from RST documentation.

This script:
1. Parses RST files to find rust-example:: directives
2. Extracts the code and rustdoc attributes
3. Generates a test crate with all examples as doc tests
4. Runs the tests and reports results

Supports both monolithic chapter files (*.rst) and per-guideline files (*.rst.inc).

Usage:
    # Extract examples and generate test crate
    uv run python scripts/extract_rust_examples.py --extract

    # Extract and test examples
    uv run python scripts/extract_rust_examples.py --test

    # Just test (assuming already extracted)
    uv run python scripts/extract_rust_examples.py --test-only

    # Output results as JSON
    uv run python scripts/extract_rust_examples.py --test --json results.json
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add scripts directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from rustdoc_utils import (
    RustExample,
    TestResult,
    compile_single_example,
    format_test_results,
    generate_test_crate,
    get_rust_version,
    load_prelude,
    process_hidden_lines,
    save_results_json,
)

# Patterns for parsing RST
RUST_EXAMPLE_PATTERN = re.compile(
    r'^([ \t]*)\.\.\ rust-example::',  # Use [ \t]* not \s* to avoid capturing newlines
    re.MULTILINE
)

CODE_BLOCK_PATTERN = re.compile(
    r'^([ \t]*)\.\.\ code-block::\ rust[ \t]*$',  # Use [ \t]* not \s* to avoid capturing newlines
    re.MULTILINE
)

EXAMPLE_DIRECTIVE_PATTERN = re.compile(
    r'^([ \t]*)\.\.\ (compliant_example|non_compliant_example)::',  # Use [ \t]* not \s*
    re.MULTILINE
)

GUIDELINE_PATTERN = re.compile(
    r'^([ \t]*)\.\.\ guideline::',  # Use [ \t]* not \s*
    re.MULTILINE
)


def parse_directive_options(content: str, start_pos: int, base_indent: str) -> Tuple[Dict[str, str], int]:
    """
    Parse options from a directive.
    
    Args:
        content: Full file content
        start_pos: Position after the directive line
        base_indent: The indentation of the directive
        
    Returns:
        Tuple of (options dict, position after options)
    """
    options = {}
    pos = start_pos
    lines = content[start_pos:].split('\n')
    option_indent = base_indent + "    "
    
    for line in lines:
        pos += len(line) + 1
        
        if not line.strip():
            continue
        
        # Check if this is an option line
        if line.startswith(option_indent) and line.strip().startswith(':'):
            # Parse option
            match = re.match(r'\s*:(\w+):\s*(.*)', line)
            if match:
                opt_name = match.group(1)
                opt_value = match.group(2).strip()
                options[opt_name] = opt_value
            continue
        
        # Check if we've moved past options (content starts)
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        
        if current_indent >= len(option_indent) and not stripped.startswith(':'):
            # This is content, not an option
            pos -= len(line) + 1  # Back up
            break
        elif current_indent < len(option_indent):
            # Dedented past directive
            pos -= len(line) + 1
            break
    
    return options, pos


def extract_directive_content(content: str, start_pos: int, base_indent: str) -> Tuple[str, int]:
    """
    Extract the content of a directive starting at the given position.
    
    Args:
        content: Full file content
        start_pos: Position after the directive options
        base_indent: The indentation of the directive
        
    Returns:
        Tuple of (extracted_content, end_position)
    """
    lines = content[start_pos:].split('\n')
    content_lines = []
    end_pos = start_pos
    content_indent = None
    in_content = False
    
    for line in lines:
        if not line.strip():
            if in_content:
                content_lines.append('')
            end_pos += len(line) + 1
            continue
        
        stripped = line.lstrip()
        current_indent = len(line) - len(stripped)
        
        if content_indent is None:
            # First non-empty line after options
            content_indent = current_indent
            if current_indent <= len(base_indent):
                # No content
                break
            in_content = True
            content_lines.append(stripped)
            end_pos += len(line) + 1
        elif current_indent >= content_indent:
            # Still in content
            relative_indent = ' ' * (current_indent - content_indent)
            content_lines.append(relative_indent + stripped)
            end_pos += len(line) + 1
        else:
            # Dedented - end of content
            break
    
    return '\n'.join(content_lines).rstrip(), end_pos


def find_parent_context(content: str, pos: int) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Find the parent directive context for a position.
    
    Args:
        content: Full file content
        pos: Position to check
        
    Returns:
        Tuple of (parent_type, parent_id, guideline_id)
    """
    before = content[:pos]
    
    # Find parent example directive
    parent_type = None
    parent_id = None
    
    example_matches = list(EXAMPLE_DIRECTIVE_PATTERN.finditer(before))
    if example_matches:
        match = example_matches[-1]
        parent_type = match.group(2)
        
        # Find ID
        after_directive = content[match.end():pos]
        id_match = re.search(r':id:\s*(\S+)', after_directive)
        parent_id = id_match.group(1) if id_match else None
    
    # Find parent guideline
    guideline_id = None
    guideline_matches = list(GUIDELINE_PATTERN.finditer(before))
    if guideline_matches:
        match = guideline_matches[-1]
        after_directive = content[match.end():pos]
        next_directive = re.search(r'\n\s*\.\. \w+::', after_directive)
        if next_directive:
            after_directive = after_directive[:next_directive.start()]
        id_match = re.search(r':id:\s*(\S+)', after_directive)
        guideline_id = id_match.group(1) if id_match else None
    
    return parent_type, parent_id, guideline_id


def extract_rust_examples_from_file(file_path: Path) -> List[RustExample]:
    """
    Extract all Rust examples from an RST file.
    
    This handles both:
    - New rust-example:: directives
    - Legacy code-block:: rust directives (for backwards compatibility during migration)
    
    Args:
        file_path: Path to the RST file (supports .rst and .rst.inc)
        
    Returns:
        List of RustExample objects
    """
    content = file_path.read_text()
    examples = []
    
    # First, find rust-example:: directives
    for match in RUST_EXAMPLE_PATTERN.finditer(content):
        indent = match.group(1)
        start = match.start()
        line_number = content[:start].count('\n') + 1
        
        # Parse options
        options, opt_end = parse_directive_options(content, match.end(), indent)
        
        # Extract content
        code, _ = extract_directive_content(content, opt_end, indent)
        
        # Process hidden lines
        display_code, full_code = process_hidden_lines(code)
        
        # Determine rustdoc attribute
        attr = None
        attr_value = None
        
        if 'ignore' in options:
            attr = 'ignore'
        elif 'compile_fail' in options:
            attr = 'compile_fail'
            attr_value = options.get('compile_fail') or None
        elif 'should_panic' in options:
            attr = 'should_panic'
            attr_value = options.get('should_panic') or None
        elif 'no_run' in options:
            attr = 'no_run'
        
        # Parse version/edition requirements
        min_version = options.get('version') or options.get('min-version')
        channel = options.get('channel', 'stable')
        edition = options.get('edition', '2021')
        
        # Find parent context
        parent_type, parent_id, guideline_id = find_parent_context(content, start)
        
        example = RustExample(
            source_file=str(file_path),
            line_number=line_number,
            code=full_code,
            display_code=display_code,
            attr=attr,
            attr_value=attr_value,
            min_version=min_version,
            channel=channel,
            edition=edition,
            example_name=options.get('name', ''),
            parent_directive=parent_type or '',
            parent_id=parent_id or '',
            guideline_id=guideline_id or '',
        )
        
        examples.append(example)
    
    # Also find legacy code-block:: rust directives within example contexts
    for match in CODE_BLOCK_PATTERN.finditer(content):
        indent = match.group(1)
        start = match.start()
        line_number = content[:start].count('\n') + 1
        
        # Check if this is inside an example directive
        parent_type, parent_id, guideline_id = find_parent_context(content, start)
        
        if not parent_type:
            # Not in an example context, skip
            continue
        
        # Check if there's already a rust-example at this location
        # (avoid double-counting during partial migration)
        already_processed = False
        for existing in examples:
            if abs(existing.line_number - line_number) < 5:
                already_processed = True
                break
        
        if already_processed:
            continue
        
        # Extract code content
        code, _ = extract_directive_content(content, match.end(), indent)
        
        example = RustExample(
            source_file=str(file_path),
            line_number=line_number,
            code=code,
            display_code=code,
            parent_directive=parent_type or '',
            parent_id=parent_id or '',
            guideline_id=guideline_id or '',
        )
        
        examples.append(example)
    
    return examples


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


def extract_all_examples(src_dirs: List[Path], quiet: bool = False) -> List[RustExample]:
    """
    Extract all Rust examples from all RST files in the given directories.
    
    Args:
        src_dirs: List of directories to scan
        quiet: If True, suppress progress output
        
    Returns:
        List of all RustExample objects found
    """
    examples = []
    
    for src_dir in src_dirs:
        all_files = find_rst_files(src_dir)
        
        if not quiet:
            print(f"🔍 Scanning {len(all_files)} RST files in {src_dir}", file=sys.stderr)
        
        # Group files by parent directory (chapter)
        files_by_chapter: Dict[str, List[Path]] = {}
        for file_path in all_files:
            # Get chapter name (parent directory relative to src_dir)
            try:
                rel_path = file_path.relative_to(src_dir)
                if len(rel_path.parts) > 1:
                    chapter = rel_path.parts[0]
                else:
                    chapter = "(root)"
            except ValueError:
                chapter = "(other)"
            
            if chapter not in files_by_chapter:
                files_by_chapter[chapter] = []
            files_by_chapter[chapter].append(file_path)
        
        # Process files grouped by chapter
        for chapter in sorted(files_by_chapter.keys()):
            chapter_files = files_by_chapter[chapter]
            chapter_has_examples = False
            file_results: List[Tuple[Path, List[RustExample]]] = []
            
            # Extract examples from each file
            for file_path in sorted(chapter_files):
                file_examples = extract_rust_examples_from_file(file_path)
                if file_examples:
                    file_results.append((file_path, file_examples))
                    examples.extend(file_examples)
                    chapter_has_examples = True
            
            # Print chapter heading and files with examples
            if chapter_has_examples and not quiet:
                print(f"\n   {chapter}/", file=sys.stderr)
                for file_path, file_examples in file_results:
                    print(f"      {file_path.name}: {len(file_examples)} examples", file=sys.stderr)
    
    if not quiet:
        print(f"\n📊 Total: {len(examples)} examples found", file=sys.stderr)
    
    return examples


def test_examples_individually(
    examples: List[RustExample],
    prelude: str = ""
) -> List[TestResult]:
    """
    Test each example individually.
    
    Args:
        examples: List of examples to test
        prelude: Optional prelude code
        
    Returns:
        List of TestResult objects
    """
    results = []
    
    # Detect current Rust version and channel
    current_version, current_channel = get_rust_version()
    if current_version:
        print(f"\n🦀 Detected Rust {current_version} ({current_channel})")
    else:
        print("\n⚠️  Could not detect Rust version")
    
    print(f"\n🧪 Testing {len(examples)} examples...")
    
    for i, example in enumerate(examples):
        result = compile_single_example(
            example, 
            prelude,
            current_version=current_version,
            current_channel=current_channel
        )
        results.append(result)
        
        # Progress indicator
        if result.skipped:
            status = "⏭️"
        elif result.passed:
            status = "✅"
        else:
            status = "❌"
        print(f"   [{i+1}/{len(examples)}] {status} {example.source_file}:{example.line_number}")
    
    return results


def analyze_requirements(examples: List[RustExample]) -> Dict:
    """
    Analyze toolchain requirements for all examples.
    
    Returns a dict with:
    - channels: dict mapping channel -> list of examples
    - versions: dict mapping min_version -> list of examples
    - editions: dict mapping edition -> list of examples
    - default: list of examples with no special requirements
    """
    requirements = {
        "channels": {"stable": [], "beta": [], "nightly": []},
        "versions": {},
        "editions": {},
        "default": [],
        "summary": {
            "total": len(examples),
            "needs_nightly": 0,
            "needs_specific_version": 0,
            "needs_old_edition": 0,
            "default_only": 0,
        }
    }
    
    for example in examples:
        example_info = {
            "file": example.source_file,
            "line": example.line_number,
            "guideline_id": example.guideline_id,
        }
        
        has_special_requirement = False
        
        # Check channel requirement
        if example.channel and example.channel != "stable":
            requirements["channels"][example.channel].append(example_info)
            has_special_requirement = True
            if example.channel == "nightly":
                requirements["summary"]["needs_nightly"] += 1
        
        # Check version requirement
        if example.min_version:
            version = example.min_version
            if version not in requirements["versions"]:
                requirements["versions"][version] = []
            requirements["versions"][version].append(example_info)
            has_special_requirement = True
            requirements["summary"]["needs_specific_version"] += 1
        
        # Check edition (track non-2021 editions)
        if example.edition and example.edition != "2021":
            edition = example.edition
            if edition not in requirements["editions"]:
                requirements["editions"][edition] = []
            requirements["editions"][edition].append(example_info)
            has_special_requirement = True
            requirements["summary"]["needs_old_edition"] += 1
        
        # Track examples with no special requirements
        if not has_special_requirement:
            requirements["default"].append(example_info)
            requirements["summary"]["default_only"] += 1
    
    return requirements


def filter_examples(
    examples: List[RustExample],
    filter_channel: Optional[str] = None,
    filter_min_version: Optional[str] = None,
    filter_default: bool = False,
) -> List[RustExample]:
    """
    Filter examples based on toolchain requirements.
    
    Args:
        examples: List of examples to filter
        filter_channel: Only include examples requiring this channel (e.g., "nightly")
        filter_min_version: Only include examples requiring at least this version
        filter_default: Only include examples with no special requirements
        
    Returns:
        Filtered list of examples
    """
    filtered = []
    
    for example in examples:
        # If filtering for default only
        if filter_default:
            has_special = (
                (example.channel and example.channel != "stable") or
                example.min_version is not None
            )
            if not has_special:
                filtered.append(example)
            continue
        
        # If filtering by channel
        if filter_channel:
            # "nightly" filter: only examples that require nightly
            if filter_channel == "nightly":
                if example.channel == "nightly":
                    filtered.append(example)
            # "stable" filter: examples that work on stable (no nightly requirement)
            elif filter_channel == "stable":
                if example.channel != "nightly":
                    filtered.append(example)
            continue
        
        # If filtering by minimum version
        if filter_min_version:
            if example.min_version:
                # Parse versions to compare
                try:
                    filter_parts = [int(x) for x in filter_min_version.split('.')[:2]]
                    example_parts = [int(x) for x in example.min_version.split('.')[:2]]
                    
                    # Include if example requires >= filter version
                    if example_parts >= filter_parts:
                        filtered.append(example)
                except ValueError:
                    # If parsing fails, include the example
                    filtered.append(example)
            continue
        
        # No filter - include all
        filtered.append(example)
    
    return filtered


def main():
    parser = argparse.ArgumentParser(
        description="Extract and test Rust examples from documentation"
    )
    
    # Actions
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract examples and generate test crate"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Extract and test examples"
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Test already extracted examples (requires --crate-dir)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Just list all examples found"
    )
    
    # Options
    parser.add_argument(
        "--src-dir",
        type=str,
        action="append",
        dest="src_dirs",
        help="Source directory to scan for RST files (can be specified multiple times)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="build/examples",
        help="Output directory for generated test crate"
    )
    parser.add_argument(
        "--prelude",
        type=str,
        default=None,
        help="Path to shared prelude file"
    )
    parser.add_argument(
        "--json",
        type=str,
        default=None,
        help="Output results to JSON file"
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Exit with error code if any tests fail"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    
    # Filtering options
    parser.add_argument(
        "--list-requirements",
        action="store_true",
        help="List toolchain requirements for all examples as JSON"
    )
    parser.add_argument(
        "--filter-channel",
        type=str,
        choices=["stable", "beta", "nightly"],
        default=None,
        help="Only test examples that require this specific channel"
    )
    parser.add_argument(
        "--filter-min-version",
        type=str,
        default=None,
        help="Only test examples that require at least this Rust version (e.g., 1.79)"
    )
    parser.add_argument(
        "--filter-default",
        action="store_true",
        help="Only test examples with no special requirements (default channel/version)"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if not any([args.extract, args.test, args.test_only, args.list, args.list_requirements]):
        parser.print_help()
        sys.exit(1)
    
    # Handle source directories - default to src/coding-guidelines if none specified
    src_dirs = args.src_dirs if args.src_dirs else ["src/coding-guidelines"]
    
    # Validate all source directories exist
    validated_src_dirs = []
    for src_dir in src_dirs:
        src_path = Path(src_dir)
        if not src_path.exists():
            print(f"❌ Source directory not found: {src_path}")
            sys.exit(1)
        validated_src_dirs.append(src_path)
    
    output_dir = Path(args.output_dir)
    
    # Load prelude
    prelude = ""
    if args.prelude:
        prelude = load_prelude(args.prelude)
        if prelude and not args.list_requirements:
            print(f"📜 Loaded prelude from {args.prelude}", file=sys.stderr)
    
    # Extract examples from all source directories
    if args.list or args.extract or args.test or args.list_requirements:
        # Use quiet mode for list-requirements to get clean JSON output
        quiet = args.list_requirements
        examples = extract_all_examples(validated_src_dirs, quiet=quiet)
        
        # Handle --list-requirements
        if args.list_requirements:
            requirements = analyze_requirements(examples)
            print(json.dumps(requirements, indent=2))
            sys.exit(0)
        
        if args.list:
            print("\n📋 Examples found:")
            for example in examples:
                attr_str = f" [{example.attr}]" if example.attr else ""
                print(f"   {example.source_file}:{example.line_number}{attr_str}")
                if args.verbose:
                    print(f"      Parent: {example.parent_directive} ({example.parent_id})")
                    print(f"      Guideline: {example.guideline_id}")
            sys.exit(0)
        
        # Apply filters if specified
        if args.filter_channel or args.filter_min_version or args.filter_default:
            original_count = len(examples)
            examples = filter_examples(
                examples,
                filter_channel=args.filter_channel,
                filter_min_version=args.filter_min_version,
                filter_default=args.filter_default,
            )
            filtered_count = original_count - len(examples)
            if filtered_count > 0:
                print(f"\n🔍 Filtered: {len(examples)} examples to test ({filtered_count} excluded)")
                if args.filter_channel:
                    print(f"   Filter: channel={args.filter_channel}")
                if args.filter_min_version:
                    print(f"   Filter: min_version>={args.filter_min_version}")
                if args.filter_default:
                    print(f"   Filter: default toolchain only (excluded {filtered_count} requiring nightly/beta or specific version)")
        
        if args.extract or args.test:
            # Generate test crate
            output_dir.mkdir(parents=True, exist_ok=True)
            crate_dir = generate_test_crate(examples, output_dir, prelude)
            print(f"\n📦 Generated test crate at {crate_dir}")
            
            # Save examples JSON for reference
            examples_json = output_dir / "examples.json"
            with open(examples_json, 'w') as f:
                json.dump([e.to_dict() for e in examples], f, indent=2)
            print(f"📄 Saved examples metadata to {examples_json}")
        
        if args.test:
            # Run tests
            results = test_examples_individually(examples, prelude)
            
            # Print results
            print(format_test_results(results))
            
            # Save JSON if requested
            if args.json:
                save_results_json(results, Path(args.json))
                print(f"\n📄 Results saved to {args.json}")
            
            # Check for failures
            failures = [r for r in results if not r.passed]
            if failures and args.fail_on_error:
                sys.exit(1)
    
    elif args.test_only:
        # Load existing examples
        examples_json = output_dir / "examples.json"
        if not examples_json.exists():
            print(f"❌ Examples file not found: {examples_json}")
            print("   Run with --extract first")
            sys.exit(1)
        
        with open(examples_json) as f:
            examples = [RustExample.from_dict(e) for e in json.load(f)]
        
        # Run tests
        results = test_examples_individually(examples, prelude)
        
        # Print results
        print(format_test_results(results))
        
        # Save JSON if requested
        if args.json:
            save_results_json(results, Path(args.json))
            print(f"\n📄 Results saved to {args.json}")
        
        # Check for failures
        failures = [r for r in results if not r.passed]
        if failures and args.fail_on_error:
            sys.exit(1)


if __name__ == "__main__":
    main()
