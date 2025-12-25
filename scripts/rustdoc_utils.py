#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Shared utilities for handling Rust code examples with rustdoc-style attributes.

This module provides common functionality used by:
- migrate_rust_examples.py: Convert existing code-block directives
- extract_rust_examples.py: Extract examples for testing
- check_rust_examples.py: Validate and test examples
"""

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Regex patterns for parsing RST
RST_CODE_BLOCK_PATTERN = re.compile(
    r'^(\s*)\.\.\ code-block::\ rust\s*$',
    re.MULTILINE
)

RST_RUST_EXAMPLE_PATTERN = re.compile(
    r'^(\s*)\.\.\ rust-example::\s*$',
    re.MULTILINE
)

# Pattern to match directive options (lines starting with :option:)
RST_OPTION_PATTERN = re.compile(r'^(\s+):(\w+):(.*)$')

# Pattern to extract content indentation
RST_CONTENT_INDENT_PATTERN = re.compile(r'^(\s+)(\S)')


@dataclass
class RustExample:
    """Represents a Rust code example extracted from documentation."""
    
    # Source location
    source_file: str
    line_number: int
    
    # The code itself
    code: str
    display_code: str  # Code as displayed (hidden lines may be stripped)
    
    # Rustdoc attributes
    attr: Optional[str] = None  # ignore, compile_fail, should_panic, no_run
    attr_value: Optional[str] = None  # e.g., error code for compile_fail
    
    # Version/edition requirements
    min_version: Optional[str] = None  # Minimum Rust version, e.g., "1.79"
    channel: str = "stable"  # stable, beta, or nightly
    edition: str = "2021"  # Rust edition: 2015, 2018, 2021, 2024
    
    # Metadata
    example_name: str = ""
    parent_directive: str = ""  # compliant_example, non_compliant_example, etc.
    parent_id: str = ""
    guideline_id: str = ""
    
    # Miri (UB detection)
    miri_mode: Optional[str] = None  # None, "check", "expect_ub", "skip"
    
    # Warning handling
    warn_mode: str = "error"  # "error" (fail on warnings) or "allow"
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'source_file': self.source_file,
            'line_number': self.line_number,
            'code': self.code,
            'display_code': self.display_code,
            'attr': self.attr,
            'attr_value': self.attr_value,
            'min_version': self.min_version,
            'channel': self.channel,
            'edition': self.edition,
            'example_name': self.example_name,
            'parent_directive': self.parent_directive,
            'parent_id': self.parent_id,
            'guideline_id': self.guideline_id,
            'miri_mode': self.miri_mode,
            'warn_mode': self.warn_mode,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'RustExample':
        """Create from dictionary."""
        return cls(
            source_file=data['source_file'],
            line_number=data['line_number'],
            code=data['code'],
            display_code=data.get('display_code', data['code']),
            attr=data.get('attr'),
            attr_value=data.get('attr_value'),
            min_version=data.get('min_version'),
            channel=data.get('channel', 'stable'),
            edition=data.get('edition', '2021'),
            example_name=data.get('example_name', ''),
            parent_directive=data.get('parent_directive', ''),
            parent_id=data.get('parent_id', ''),
            guideline_id=data.get('guideline_id', ''),
            miri_mode=data.get('miri_mode'),
            warn_mode=data.get('warn_mode', 'error'),
        )


@dataclass
class TestResult:
    """Result of testing a single Rust example."""
    
    example: RustExample
    passed: bool
    expected_to_fail: bool = False
    skipped: bool = False
    skip_reason: str = ""
    error_message: str = ""
    compiler_output: str = ""
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'example': self.example.to_dict(),
            'passed': self.passed,
            'expected_to_fail': self.expected_to_fail,
            'skipped': self.skipped,
            'skip_reason': self.skip_reason,
            'error_message': self.error_message,
            'compiler_output': self.compiler_output,
            'warnings': self.warnings,
        }


def process_hidden_lines(code: str) -> Tuple[str, str]:
    """
    Process code to separate hidden lines (prefixed with `# `).
    
    Rustdoc convention:
    - Lines starting with `# ` (hash + space) are hidden in docs but compiled
    - Lines starting with `##` become `#` in the output
    
    Args:
        code: The raw code with potential hidden line markers
        
    Returns:
        Tuple of (display_code, full_code_for_testing)
    """
    lines = code.split('\n')
    display_lines = []
    full_lines = []
    
    for line in lines:
        if line.startswith('# '):
            # Hidden line - include in full code without the marker
            full_lines.append(line[2:])
        elif line == '#':
            # Empty hidden line
            full_lines.append('')
        elif line.startswith('## '):
            # Escaped hash - show as single hash
            display_lines.append('#' + line[2:])
            full_lines.append('#' + line[2:])
        else:
            display_lines.append(line)
            full_lines.append(line)
    
    return '\n'.join(display_lines), '\n'.join(full_lines)


def get_rust_version() -> Tuple[Optional[str], str]:
    """
    Get the current Rust compiler version and channel.
    
    Returns:
        Tuple of (version_string, channel) where version_string is like "1.75.0"
        and channel is "stable", "beta", or "nightly".
        Returns (None, "unknown") if rustc is not available.
    """
    try:
        result = subprocess.run(
            ['rustc', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            return None, "unknown"
        
        # Parse version string like "rustc 1.75.0 (82e1608df 2023-12-21)"
        # or "rustc 1.79.0-nightly (abc123 2024-01-01)"
        output = result.stdout.strip()
        match = re.search(r'rustc (\d+\.\d+\.\d+)(?:-(\w+))?', output)
        if match:
            version = match.group(1)
            channel = match.group(2) if match.group(2) else "stable"
            # Normalize channel names
            if channel not in ("stable", "beta", "nightly"):
                channel = "stable"  # Release versions without suffix are stable
            return version, channel
        return None, "unknown"
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return None, "unknown"


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """
    Parse a version string into a tuple of (major, minor, patch).
    
    Args:
        version_str: Version string like "1.75" or "1.75.0"
        
    Returns:
        Tuple of (major, minor, patch)
    """
    parts = version_str.split('.')
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return (major, minor, patch)


def version_satisfied(current: str, required: str) -> bool:
    """
    Check if the current version satisfies the minimum required version.
    
    Args:
        current: Current Rust version (e.g., "1.75.0")
        required: Minimum required version (e.g., "1.79")
        
    Returns:
        True if current >= required
    """
    current_tuple = parse_version(current)
    required_tuple = parse_version(required)
    return current_tuple >= required_tuple


def channel_satisfied(current: str, required: str) -> bool:
    """
    Check if the current channel satisfies the required channel.
    
    Channel hierarchy: nightly > beta > stable
    - stable code can run on any channel
    - beta code can run on beta or nightly
    - nightly code can only run on nightly
    
    Args:
        current: Current Rust channel
        required: Required channel
        
    Returns:
        True if current channel can run the required code
    """
    channel_order = {"stable": 0, "beta": 1, "nightly": 2}
    current_level = channel_order.get(current, 0)
    required_level = channel_order.get(required, 0)
    return current_level >= required_level


def add_hidden_lines(code: str, hidden_prefix: str = "") -> str:
    """
    Add hidden line markers to code.
    
    Args:
        code: The code to add markers to
        hidden_prefix: Lines starting with this will be marked as hidden
        
    Returns:
        Code with hidden line markers added
    """
    if not hidden_prefix:
        return code
    
    lines = code.split('\n')
    result_lines = []
    
    for line in lines:
        if line.strip().startswith(hidden_prefix):
            result_lines.append('# ' + line)
        else:
            result_lines.append(line)
    
    return '\n'.join(result_lines)


def wrap_in_main(code: str) -> str:
    """
    Wrap code in a main function if it doesn't have one.
    
    This is similar to what rustdoc does for doc tests.
    """
    # Check if code already has a main function
    if re.search(r'\bfn\s+main\s*\(', code):
        return code
    
    # Check if it has any function definitions at all
    has_functions = re.search(r'\bfn\s+\w+\s*[<(]', code)
    has_impl = re.search(r'\bimpl\b', code)
    has_struct = re.search(r'\bstruct\b', code)
    has_enum = re.search(r'\benum\b', code)
    has_trait = re.search(r'\btrait\b', code)
    has_use = re.search(r'\buse\b', code)
    has_mod = re.search(r'\bmod\b', code)
    has_const = re.search(r'\bconst\b', code)
    has_static = re.search(r'\bstatic\b', code)
    has_type = re.search(r'\btype\b', code)
    
    # If it looks like top-level items, don't wrap
    if has_functions or has_impl or has_struct or has_enum or has_trait or has_mod or has_type:
        # But we might still need a main if there's code outside functions
        return code
    
    # If it's just statements, wrap in main
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


def load_prelude(prelude_path: Optional[str], required: bool = True) -> str:
    """
    Load the shared prelude file.
    
    Args:
        prelude_path: Path to the prelude file
        required: If True, exit with error if file not found
        
    Returns:
        Contents of the prelude file, or empty string if not provided
    """
    if not prelude_path:
        return ""
    
    path = Path(prelude_path)
    if path.exists():
        return path.read_text()
    
    # File specified but not found
    if required:
        print(f"❌ Error: Prelude file not found: {prelude_path}")
        print("   Examples that use ArithmeticError, DivError, etc. will fail without the prelude.")
        import sys
        sys.exit(1)
    else:
        print(f"⚠️  Warning: Prelude file not found: {prelude_path}")
        return ""


def generate_doctest(
    example: RustExample,
    prelude: str = "",
    wrap_main: bool = True
) -> str:
    """
    Generate a rustdoc-style doctest from an example.
    
    Args:
        example: The example to convert
        prelude: Optional prelude code to prepend
        wrap_main: Whether to wrap in main() if needed
        
    Returns:
        The complete test code
    """
    code = example.code
    
    # Extract inner attributes (like #![feature(...)]) - they must be at file start
    inner_attrs = []
    remaining_lines = []
    for line in code.split('\n'):
        stripped = line.strip()
        if stripped.startswith('#![') and not remaining_lines:
            # This is an inner attribute at the start of code
            inner_attrs.append(line)
        elif not stripped and not remaining_lines:
            # Skip leading blank lines before checking for more inner attrs
            continue
        else:
            remaining_lines.append(line)
    
    # Reconstruct code without leading inner attributes
    code = '\n'.join(remaining_lines)
    
    # Build final code: inner attrs first, then prelude, then code
    parts = []
    if inner_attrs:
        parts.append('\n'.join(inner_attrs))
    if prelude:
        parts.append(prelude)
    parts.append(code)
    
    code = '\n\n'.join(parts)
    
    # Wrap in main if needed
    if wrap_main:
        code = wrap_in_main(code)
    
    return code


def generate_test_crate(
    examples: List[RustExample],
    output_dir: Path,
    prelude: str = "",
    crate_name: str = "guidelines_examples"
) -> Path:
    """
    Generate a Cargo crate containing all examples as doc tests.
    
    Args:
        examples: List of examples to include
        output_dir: Directory to create the crate in
        prelude: Optional shared prelude code
        crate_name: Name for the generated crate
        
    Returns:
        Path to the generated crate
    """
    crate_dir = output_dir / crate_name
    crate_dir.mkdir(parents=True, exist_ok=True)
    
    # Create Cargo.toml
    cargo_toml = f"""[package]
name = "{crate_name}"
version = "0.1.0"
edition = "2021"

[lib]
doctest = true
"""
    (crate_dir / "Cargo.toml").write_text(cargo_toml)
    
    # Create src directory
    src_dir = crate_dir / "src"
    src_dir.mkdir(exist_ok=True)
    
    # Generate lib.rs with all examples as doc tests
    lib_content = generate_lib_rs(examples, prelude)
    (src_dir / "lib.rs").write_text(lib_content)
    
    return crate_dir


def generate_lib_rs(examples: List[RustExample], prelude: str = "") -> str:
    """
    Generate lib.rs content with all examples as doc tests.
    
    Args:
        examples: List of examples to include
        prelude: Optional shared prelude code
        
    Returns:
        The lib.rs content
    """
    sections = []
    
    # Add module-level documentation with examples
    sections.append("//! # Coding Guidelines Examples")
    sections.append("//!")
    sections.append("//! This crate contains all code examples from the Safety-Critical Rust Coding Guidelines.")
    sections.append("//! Each example is tested as a rustdoc test.")
    sections.append("")
    
    for i, example in enumerate(examples):
        # Generate a unique function/module for each example
        example_id = example.example_name or f"example_{i}"
        safe_id = re.sub(r'[^a-zA-Z0-9_]', '_', example_id)
        
        # Build the rustdoc attribute
        attr_line = ""
        if example.attr == 'ignore':
            attr_line = "/// ```ignore"
        elif example.attr == 'compile_fail':
            if example.attr_value:
                attr_line = f"/// ```compile_fail,{example.attr_value}"
            else:
                attr_line = "/// ```compile_fail"
        elif example.attr == 'should_panic':
            if example.attr_value:
                attr_line = f'/// ```should_panic = "{example.attr_value}"'
            else:
                attr_line = "/// ```should_panic"
        elif example.attr == 'no_run':
            attr_line = "/// ```no_run"
        else:
            attr_line = "/// ```"
        
        # Build the doc comment
        sections.append(f"/// Example from {example.source_file}:{example.line_number}")
        if example.parent_id:
            sections.append(f"/// Parent: {example.parent_id}")
        sections.append("///")
        sections.append(attr_line)
        
        # Add prelude as hidden lines if present
        if prelude:
            for line in prelude.split('\n'):
                if line.strip():
                    sections.append(f"/// # {line}")
        
        # Add the example code
        code = example.code
        for line in code.split('\n'):
            sections.append(f"/// {line}")
        
        sections.append("/// ```")
        sections.append(f"pub fn {safe_id}() {{}}")
        sections.append("")
    
    return '\n'.join(sections)


def run_doctests(crate_dir: Path) -> Tuple[bool, str, List[TestResult]]:
    """
    Run cargo test --doc on a generated crate.
    
    Args:
        crate_dir: Path to the crate directory
        
    Returns:
        Tuple of (all_passed, output, list of TestResult)
    """
    try:
        result = subprocess.run(
            ["cargo", "test", "--doc"],
            cwd=crate_dir,
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        output = result.stdout + "\n" + result.stderr
        passed = result.returncode == 0
        
        return passed, output, []
        
    except subprocess.TimeoutExpired:
        return False, "Test execution timed out", []
    except Exception as e:
        return False, f"Error running tests: {e}", []


def compile_single_example(
    example: RustExample,
    prelude: str = "",
    current_version: Optional[str] = None,
    current_channel: str = "stable"
) -> TestResult:
    """
    Compile a single example and check if it meets expectations.
    
    Args:
        example: The example to compile
        prelude: Optional prelude code
        current_version: Current Rust version (detected if not provided)
        current_channel: Current Rust channel (detected if not provided)
        
    Returns:
        TestResult with compilation outcome
    """
    # Check version compatibility
    if example.min_version and current_version:
        if not version_satisfied(current_version, example.min_version):
            return TestResult(
                example=example,
                passed=True,  # Not a failure, just skipped
                skipped=True,
                skip_reason=f"Requires Rust {example.min_version}+ (have {current_version})",
            )
    
    # Check channel compatibility
    if example.channel and example.channel != "stable":
        if not channel_satisfied(current_channel, example.channel):
            return TestResult(
                example=example,
                passed=True,  # Not a failure, just skipped
                skipped=True,
                skip_reason=f"Requires {example.channel} channel (have {current_channel})",
            )
    
    # Skip ignored examples
    if example.attr == 'ignore':
        return TestResult(
            example=example,
            passed=True,
            expected_to_fail=False,
            skipped=True,
            skip_reason="ignore attribute",
        )
    
    # Determine expected outcome
    should_fail = example.attr == 'compile_fail'
    
    # Generate the test code
    code = generate_doctest(example, prelude, wrap_main=True)
    
    # Write to temp file and compile
    with tempfile.TemporaryDirectory() as tmpdir:
        src_file = Path(tmpdir) / "test.rs"
        src_file.write_text(code)
        
        try:
            out_file = Path(tmpdir) / "test_binary"
            edition = example.edition or "2021"
            result = subprocess.run(
                ["rustc", f"--edition={edition}", "--crate-type=bin", "-o", str(out_file), str(src_file)],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            compiled_successfully = result.returncode == 0
            compiler_output = result.stderr
            
            # Check for warnings
            warnings = []
            if 'warning:' in compiler_output or 'warning[' in compiler_output:
                for line in compiler_output.split('\n'):
                    if 'warning:' in line or 'warning[' in line:
                        warnings.append(line)
            
            if should_fail:
                # Expected to fail
                if compiled_successfully:
                    return TestResult(
                        example=example,
                        passed=False,
                        expected_to_fail=True,
                        error_message="Expected compilation to fail, but it succeeded",
                        compiler_output=compiler_output,
                        warnings=warnings,
                    )
                else:
                    # Check error code if specified
                    if example.attr_value:
                        if example.attr_value in compiler_output:
                            return TestResult(
                                example=example,
                                passed=True,
                                expected_to_fail=True,
                                compiler_output=compiler_output,
                                warnings=warnings,
                            )
                        else:
                            return TestResult(
                                example=example,
                                passed=False,
                                expected_to_fail=True,
                                error_message=f"Expected error {example.attr_value} not found in output",
                                compiler_output=compiler_output,
                                warnings=warnings,
                            )
                    else:
                        return TestResult(
                            example=example,
                            passed=True,
                            expected_to_fail=True,
                            compiler_output=compiler_output,
                            warnings=warnings,
                        )
            else:
                # Expected to compile
                if compiled_successfully:
                    # Check warn_mode - if "error" and there are warnings, fail
                    if example.warn_mode == "error" and warnings:
                        return TestResult(
                            example=example,
                            passed=False,
                            expected_to_fail=False,
                            error_message="Compilation succeeded but produced warnings",
                            compiler_output=compiler_output,
                            warnings=warnings,
                        )
                    return TestResult(
                        example=example,
                        passed=True,
                        expected_to_fail=False,
                        warnings=warnings,
                    )
                else:
                    return TestResult(
                        example=example,
                        passed=False,
                        expected_to_fail=False,
                        error_message="Compilation failed unexpectedly",
                        compiler_output=compiler_output,
                        warnings=warnings,
                    )
                    
        except subprocess.TimeoutExpired:
            return TestResult(
                example=example,
                passed=False,
                expected_to_fail=should_fail,
                error_message="Compilation timed out",
            )
        except Exception as e:
            return TestResult(
                example=example,
                passed=False,
                expected_to_fail=should_fail,
                error_message=f"Error: {e}",
            )


def format_test_results(results: List[TestResult]) -> str:
    """
    Format test results for display.
    
    Args:
        results: List of test results
        
    Returns:
        Formatted string
    """
    lines = []
    passed = sum(1 for r in results if r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.passed)
    with_warnings = sum(1 for r in results if r.warnings and r.passed)
    
    lines.append(f"{'='*60}")
    if skipped:
        lines.append(f"Test Results: {passed} passed, {failed} failed, {skipped} skipped")
    else:
        lines.append(f"Test Results: {passed} passed, {failed} failed")
    if with_warnings:
        lines.append(f"             ({with_warnings} passed with warnings)")
    lines.append(f"{'='*60}")
    
    # Show failures first
    failures = [r for r in results if not r.passed]
    if failures:
        lines.append("\nFAILURES:")
        lines.append("-" * 40)
        
        for result in failures:
            example = result.example
            lines.append(f"\n📍 {example.source_file}:{example.line_number}")
            if example.parent_id:
                lines.append(f"   Parent: {example.parent_id}")
            lines.append(f"   ❌ {result.error_message}")
            
            if result.compiler_output:
                lines.append("   Compiler output:")
                for line in result.compiler_output.split('\n')[:20]:  # Limit output
                    lines.append(f"      {line}")
                if len(result.compiler_output.split('\n')) > 20:
                    lines.append("      ... (truncated)")
    
    # Show skipped tests
    skipped_results = [r for r in results if r.skipped]
    if skipped_results:
        lines.append("\nSKIPPED:")
        lines.append("-" * 40)
        
        for result in skipped_results:
            example = result.example
            lines.append(f"\n⏭️  {example.source_file}:{example.line_number}")
            lines.append(f"   {result.skip_reason}")
    
    return '\n'.join(lines)


def save_results_json(results: List[TestResult], output_path: Path):
    """Save test results to JSON file."""
    passed = sum(1 for r in results if r.passed and not r.skipped)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.passed)
    with_warnings = sum(1 for r in results if r.warnings and r.passed)
    
    data = {
        'total': len(results),
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'with_warnings': with_warnings,
        'results': [r.to_dict() for r in results],
    }
    
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
