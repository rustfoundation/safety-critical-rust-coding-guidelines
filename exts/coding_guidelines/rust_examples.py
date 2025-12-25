# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Sphinx extension providing the `rust-example` directive for code examples
with rustdoc-style attributes for compilation testing.

Supported attributes:
- ignore: Don't compile this example
- compile_fail: Example should fail to compile (optionally with error code)
- should_panic: Example should compile but panic at runtime
- no_run: Compile but don't run the example
- miri: Run Miri (UB detector) - values: empty (check), "expect_ub", "skip"

Hidden lines (prefixed with `# `) can be shown or hidden via interactive toggle.

Interactive features (via JavaScript post-processing):
- Copy button: Copies full code including hidden lines
- Run button: Executes code on Rust Playground
- Miri button: Runs code through Miri for UB detection (when :miri: set)
- Toggle button: Shows/hides hidden lines

The directive outputs standard docutils nodes which Sphinx processes normally.
JavaScript then enhances the rendered HTML with interactive buttons by finding
elements with the 'rust-example-container' class.
"""

import json
import os
import re
import tomllib
from pathlib import Path
from typing import List, Optional, Tuple

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from pygments import highlight
from pygments.lexers import RustLexer
from pygments.formatters import HtmlFormatter
from sphinx.application import Sphinx
from sphinx.errors import SphinxError
from sphinx.util import logging

from .common import bar_format, get_tqdm

logger = logging.getLogger(__name__)


class MiriValidationError(SphinxError):
    """Error raised when unsafe code is missing :miri: option."""
    category = "Miri Validation Error"


# Valid rustdoc attributes
RUSTDOC_ATTRIBUTES = {
    "ignore": "This example is not compiled or tested",
    "compile_fail": "This example should fail to compile",
    "should_panic": "This example should panic at runtime",
    "no_run": "This example is compiled but not executed",
}

# Miri mode values
MIRI_MODES = {"check", "expect_ub", "skip"}

# Options incompatible with :miri: (code must compile and run for Miri)
MIRI_INCOMPATIBLE_OPTIONS = {"ignore", "compile_fail", "no_run"}


class RustExamplesConfig:
    """Configuration loaded from rust_examples_config.toml"""
    
    def __init__(self):
        self.edition = "2021"
        self.channel = "stable"
        self.version = "1.85.0"
        self.playground_api_url = "https://play.rust-lang.org"
        self.version_mismatch_threshold = 2
        # Miri settings
        self.miri_require_for_unsafe = True
        self.miri_timeout = 60
    
    @classmethod
    def load(cls, config_path: Path) -> "RustExamplesConfig":
        """
        Load configuration from TOML file.
        
        Args:
            config_path: Path to the TOML configuration file
            
        Returns:
            RustExamplesConfig instance
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            tomllib.TOMLDecodeError: If config file is invalid
        """
        config = cls()
        
        if not config_path.exists():
            raise FileNotFoundError(f"Rust examples config not found: {config_path}")
        
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        
        defaults = data.get("defaults", {})
        config.edition = defaults.get("edition", config.edition)
        config.channel = defaults.get("channel", config.channel)
        config.version = defaults.get("version", config.version)
        
        playground = data.get("playground", {})
        config.playground_api_url = playground.get("api_url", config.playground_api_url)
        
        warnings = data.get("warnings", {})
        config.version_mismatch_threshold = warnings.get(
            "version_mismatch_threshold", 
            config.version_mismatch_threshold
        )
        
        # Miri settings
        miri = data.get("miri", {})
        config.miri_require_for_unsafe = miri.get("require_for_unsafe", config.miri_require_for_unsafe)
        config.miri_timeout = miri.get("timeout", config.miri_timeout)
        
        return config


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """Parse a version string into (major, minor, patch) tuple."""
    parts = version_str.split(".")
    major = int(parts[0]) if len(parts) > 0 else 0
    minor = int(parts[1]) if len(parts) > 1 else 0
    patch = int(parts[2]) if len(parts) > 2 else 0
    return (major, minor, patch)


def version_diff(v1: str, v2: str) -> int:
    """Calculate the minor version difference between two versions."""
    try:
        maj1, min1, _ = parse_version(v1)
        maj2, min2, _ = parse_version(v2)
        
        if maj1 != maj2:
            return (maj2 - maj1) * 100 + (min2 - min1)
        
        return min2 - min1
    except (ValueError, IndexError):
        return 0


def parse_compile_fail_error(value: str) -> Tuple[bool, Optional[str]]:
    """Parse compile_fail option value."""
    if not value or value.lower() in ("true", "yes", "1"):
        return (True, None)
    if re.match(r"^E\d{4}$", value.strip()):
        return (True, value.strip())
    return (True, None)


def parse_miri_option(value: Optional[str]) -> Tuple[str, Optional[str]]:
    """
    Parse :miri: option value.
    
    Args:
        value: The option value (empty string, "expect_ub", "skip", or future "expect_ub(pattern)")
        
    Returns:
        (mode, pattern) where:
        - mode: "check" | "expect_ub" | "skip"
        - pattern: Optional UB pattern for future use (None for now)
    
    Examples:
        None or "" -> ("check", None)
        "expect_ub" -> ("expect_ub", None)
        "skip" -> ("skip", None)
        "expect_ub(unaligned)" -> ("expect_ub", "unaligned")  # Future
    """
    if value is None or value.strip() == "":
        return ("check", None)
    
    value = value.strip()
    
    # Check for future pattern syntax: expect_ub(pattern)
    match = re.match(r"^expect_ub\(([^)]+)\)$", value)
    if match:
        return ("expect_ub", match.group(1))
    
    if value == "expect_ub":
        return ("expect_ub", None)
    
    if value == "skip":
        return ("skip", None)
    
    # Unknown value - treat as check but log warning
    logger.warning(f"Unknown :miri: value '{value}', treating as 'check'")
    return ("check", None)


def contains_unsafe_keyword(code: str) -> bool:
    """
    Check if code contains the `unsafe` keyword outside of comments and strings.
    
    This is a simplified tokenizer that handles:
    - Line comments (// ...)
    - Block comments (/* ... */)
    - String literals ("..." and r#"..."#)
    - Character literals ('...')
    - Raw strings (r"...", r#"..."#, etc.)
    
    Args:
        code: Rust source code
        
    Returns:
        True if `unsafe` keyword is found in code context
    """
    # States for the simple tokenizer
    i = 0
    length = len(code)
    
    while i < length:
        # Skip line comments
        if i < length - 1 and code[i:i+2] == '//':
            while i < length and code[i] != '\n':
                i += 1
            continue
        
        # Skip block comments (handles nested)
        if i < length - 1 and code[i:i+2] == '/*':
            i += 2
            depth = 1
            while i < length - 1 and depth > 0:
                if code[i:i+2] == '/*':
                    depth += 1
                    i += 2
                elif code[i:i+2] == '*/':
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        
        # Skip raw strings: r"...", r#"..."#, r##"..."##, etc.
        if code[i] == 'r' and i < length - 1:
            j = i + 1
            hash_count = 0
            while j < length and code[j] == '#':
                hash_count += 1
                j += 1
            if j < length and code[j] == '"':
                # Found raw string start
                j += 1
                # Find the matching end: "### with same number of hashes
                end_pattern = '"' + '#' * hash_count
                while j < length:
                    if code[j:j+len(end_pattern)] == end_pattern:
                        j += len(end_pattern)
                        break
                    j += 1
                i = j
                continue
        
        # Skip regular strings
        if code[i] == '"':
            i += 1
            while i < length:
                if code[i] == '\\' and i < length - 1:
                    i += 2  # Skip escaped character
                elif code[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            continue
        
        # Skip character literals
        if code[i] == "'":
            # Could be a char literal or a lifetime
            # Char literals: 'a', '\n', '\x00', etc.
            # Lifetimes: 'a, 'static
            if i < length - 1:
                j = i + 1
                if j < length and code[j] == '\\':
                    # Escaped char
                    j += 1
                    while j < length and code[j] != "'":
                        j += 1
                    if j < length:
                        j += 1
                    i = j
                    continue
                elif j < length - 1 and code[j+1] == "'":
                    # Simple char like 'a'
                    i = j + 2
                    continue
                # Otherwise it's a lifetime, continue normally
        
        # Check for `unsafe` keyword
        if code[i:i+6] == 'unsafe':
            # Make sure it's a word boundary (not part of another identifier)
            before_ok = (i == 0 or not (code[i-1].isalnum() or code[i-1] == '_'))
            after_pos = i + 6
            after_ok = (after_pos >= length or not (code[after_pos].isalnum() or code[after_pos] == '_'))
            if before_ok and after_ok:
                return True
        
        i += 1
    
    return False


def process_hidden_lines(code: str, show_hidden: bool = False) -> Tuple[str, str, List[int]]:
    """
    Process code to handle hidden lines (prefixed with `# `).
    
    Args:
        code: The raw code with potential hidden line markers
        show_hidden: Whether to include hidden lines in rendered output
        
    Returns:
        Tuple of (display_code, full_code_for_testing, hidden_line_numbers)
        hidden_line_numbers is 0-indexed list of lines that are hidden
    """
    lines = code.split('\n')
    display_lines = []
    full_lines = []
    hidden_line_numbers = []
    
    for i, line in enumerate(lines):
        if line.startswith('# ') or line == '#':
            full_lines.append(line[2:] if line.startswith('# ') else '')
            hidden_line_numbers.append(i)
            if show_hidden:
                display_lines.append(line)
        else:
            display_lines.append(line)
            full_lines.append(line)
    
    return '\n'.join(display_lines), '\n'.join(full_lines), hidden_line_numbers


def highlight_code_with_hidden_lines(full_code: str, hidden_line_numbers: List[int]) -> str:
    """
    Highlight code using Pygments and wrap hidden lines with a marker class.
    
    Args:
        full_code: The complete code (hidden lines already stripped of # prefix)
        hidden_line_numbers: 0-indexed list of which lines were hidden
        
    Returns:
        HTML string with syntax highlighting and hidden lines wrapped
    """
    # Use Pygments to highlight the full code
    lexer = RustLexer()
    # Use a formatter that doesn't wrap in <pre> - we just want the highlighted spans
    formatter = HtmlFormatter(nowrap=True)
    highlighted = highlight(full_code, lexer, formatter)
    
    # Now we need to wrap hidden lines with our marker class
    # Split by newlines, being careful to preserve the HTML structure
    lines = highlighted.split('\n')
    hidden_set = set(hidden_line_numbers)
    
    result_lines = []
    for i, line in enumerate(lines):
        if i in hidden_set:
            # Wrap the entire line content in a span (no # prefix - just visual styling)
            result_lines.append(f'<span class="rust-hidden-line">{line}</span>')
        else:
            result_lines.append(line)
    
    return '\n'.join(result_lines)


class RustExampleDirective(Directive):
    """
    A directive for Rust code examples with rustdoc-style attributes.
    
    Usage:
        .. rust-example::
            :compile_fail: E0277
            
            fn example() {
                let x: i32 = "string"; // This fails
            }
        
        .. rust-example::
            :ignore:
            :edition: 2018
            :channel: nightly
            :version: 1.79.0
            
            # use std::collections::HashMap;
            # fn main() {
            let map = HashMap::new();
            # }
    """
    
    has_content = True
    required_arguments = 0
    optional_arguments = 0
    final_argument_whitespace = True
    
    option_spec = {
        # Rustdoc attributes
        "ignore": directives.flag,
        "compile_fail": directives.unchanged,
        "should_panic": directives.unchanged,
        "no_run": directives.flag,
        # Miri (UB detection)
        "miri": directives.unchanged,  # Values: "" (check), "expect_ub", "skip"
        # Toolchain options
        "edition": directives.unchanged,
        "channel": directives.unchanged,
        "version": directives.unchanged,
        # Display options
        "show_hidden": directives.flag,
        # Metadata
        "name": directives.unchanged,
    }
    
    def run(self) -> List[nodes.Node]:
        env = self.state.document.settings.env
        
        # Load configuration (with fallback defaults)
        config = getattr(env, 'rust_examples_config', None)
        if config is None:
            config_path = Path(env.app.confdir) / "rust_examples_config.toml"
            try:
                config = RustExamplesConfig.load(config_path)
            except FileNotFoundError:
                logger.warning(f"Rust examples config not found at {config_path}, using defaults")
                config = RustExamplesConfig()
            except Exception as e:
                logger.error(f"Error loading rust examples config: {e}")
                config = RustExamplesConfig()
            env.rust_examples_config = config
        
        # Get configuration for showing hidden lines
        show_hidden_global = getattr(env.config, 'rust_examples_show_hidden', False)
        show_hidden = 'show_hidden' in self.options or show_hidden_global
        
        # Parse the code content
        raw_code = '\n'.join(self.content)
        display_code, full_code, hidden_line_numbers = process_hidden_lines(raw_code, show_hidden)
        
        # Determine rustdoc attribute
        rustdoc_attr = None
        attr_value = None
        
        if 'ignore' in self.options:
            rustdoc_attr = 'ignore'
        elif 'compile_fail' in self.options:
            rustdoc_attr = 'compile_fail'
            _, attr_value = parse_compile_fail_error(self.options.get('compile_fail', ''))
        elif 'should_panic' in self.options:
            rustdoc_attr = 'should_panic'
            attr_value = self.options.get('should_panic', None)
            if attr_value in ('', None):
                attr_value = None
        elif 'no_run' in self.options:
            rustdoc_attr = 'no_run'
        
        # Parse Miri option
        miri_mode = None
        miri_pattern = None
        has_miri_option = 'miri' in self.options
        
        # Store source location (needed for error messages)
        source, line = self.state_machine.get_source_and_line(self.lineno)
        
        if has_miri_option:
            miri_mode, miri_pattern = parse_miri_option(self.options.get('miri', ''))
            
            # Validate: miri cannot be combined with ignore, compile_fail, or no_run
            if rustdoc_attr in MIRI_INCOMPATIBLE_OPTIONS:
                logger.error(
                    f"{source}:{line}: :miri: cannot be used with :{rustdoc_attr}: "
                    f"(Miri requires code that compiles and runs)"
                )
                # Create an error node instead of normal content
                error_node = nodes.error()
                error_para = nodes.paragraph()
                error_para += nodes.Text(
                    f"Configuration error: :miri: cannot be used with :{rustdoc_attr}:"
                )
                error_node += error_para
                return [error_node]
        
        # Check for unsafe code without miri option (build enforcement)
        # Note: The actual enforcement happens in check_miri_violations at consistency time
        # This warning provides immediate feedback during document processing
        code_has_unsafe = contains_unsafe_keyword(full_code)
        require_miri_for_unsafe = getattr(env.config, 'rust_examples_require_miri_for_unsafe', 
                                          config.miri_require_for_unsafe)
        
        if code_has_unsafe and not has_miri_option and require_miri_for_unsafe:
            logger.warning(
                f"{source}:{line}: Example contains `unsafe` code but no :miri: option. "
                f"Add :miri: (check for UB), :miri: expect_ub (if demonstrating UB), "
                f"or :miri: skip (to opt out)."
            )
        
        # Get toolchain options
        edition = self.options.get('edition', config.edition)
        channel = self.options.get('channel', config.channel)
        version = self.options.get('version', config.version)
        
        # Determine expected outcome
        expected_outcome = "success"
        if rustdoc_attr == "compile_fail":
            expected_outcome = "compile_fail"
        elif rustdoc_attr == "should_panic":
            expected_outcome = "should_panic"
        elif rustdoc_attr == "no_run":
            expected_outcome = "no_run"
        
        is_runnable = rustdoc_attr != "ignore"
        has_hidden_lines = len(hidden_line_numbers) > 0
        version_mismatch = version_diff(version, config.version) >= config.version_mismatch_threshold
        show_channel_badge = channel == "nightly"
        
        # Determine if Miri button should be shown (miri set and not skip)
        show_miri_button = miri_mode is not None and miri_mode != "skip"
        
        # Build JSON data for JavaScript
        js_data = {
            "code": full_code,
            "displayCode": display_code,
            "hiddenLineNumbers": hidden_line_numbers,
            "edition": edition,
            "channel": channel,
            "version": version,
            "expectedOutcome": expected_outcome,
            "expectedError": attr_value if rustdoc_attr == "compile_fail" else None,
            "runnable": is_runnable,
            "hasHiddenLines": has_hidden_lines,
        }
        
        # Add Miri data if miri option is set
        if miri_mode is not None:
            js_data["miri"] = {
                "mode": miri_mode,
                "pattern": miri_pattern,
            }
        
        # If there are hidden lines, pre-generate the highlighted HTML for the full code
        if has_hidden_lines:
            js_data["fullCodeHighlighted"] = highlight_code_with_hidden_lines(
                full_code, hidden_line_numbers
            )
        
        # Create the outer container
        container = nodes.container()
        container['classes'].append('rust-example-container')
        
        # Determine if we need badges
        show_miri_badge = miri_mode is not None and miri_mode != "skip"
        needs_badges = rustdoc_attr or show_channel_badge or version_mismatch or show_miri_badge
        
        # Add badge container if needed
        if needs_badges:
            badge_container = nodes.container()
            badge_container['classes'].append('rust-example-badges')
            
            if rustdoc_attr:
                badge = nodes.inline()
                badge['classes'].append('rust-example-badge')
                badge['classes'].append(f'rust-example-badge-{rustdoc_attr.replace("_", "-")}')
                badge_text = rustdoc_attr.replace("_", " ")
                if attr_value:
                    badge_text += f"({attr_value})"
                badge += nodes.Text(badge_text)
                badge_container += badge
            
            # Miri badge
            if show_miri_badge:
                badge = nodes.inline()
                badge['classes'].append('rust-example-badge')
                if miri_mode == "expect_ub":
                    badge['classes'].append('rust-example-badge-miri-expect-ub')
                    badge += nodes.Text('undefined behavior')
                else:
                    badge['classes'].append('rust-example-badge-miri')
                    badge += nodes.Text('miri')
                badge_container += badge
            
            if show_channel_badge:
                badge = nodes.inline()
                badge['classes'].append('rust-example-badge')
                badge['classes'].append('rust-example-badge-nightly')
                badge += nodes.Text('nightly')
                badge_container += badge
            
            if version_mismatch:
                badge = nodes.inline()
                badge['classes'].append('rust-example-badge')
                badge['classes'].append('rust-example-badge-version')
                badge += nodes.Text(f'Rust {version} ⚠️')
                badge_container += badge
            
            container += badge_container
        
        # Create the code block - Sphinx will syntax highlight this
        code_node = nodes.literal_block(display_code, display_code)
        code_node['language'] = 'rust'
        code_node['classes'].append('rust-example-code')
        
        # Store metadata on the code node for potential extraction
        code_node['rustdoc_attr'] = rustdoc_attr
        code_node['rustdoc_attr_value'] = attr_value
        code_node['rustdoc_full_code'] = full_code
        code_node['rustdoc_example_name'] = self.options.get('name', '')
        code_node['rustdoc_edition'] = edition
        code_node['rustdoc_channel'] = channel
        code_node['rustdoc_version'] = version
        code_node['rustdoc_miri_mode'] = miri_mode
        code_node['rustdoc_miri_pattern'] = miri_pattern
        code_node['source'] = source
        code_node['line'] = line
        
        container += code_node
        
        # Add a hidden element with the JSON data for JavaScript
        json_str = json.dumps(js_data)
        json_node = nodes.raw(
            '',
            f'<script type="application/json" class="rust-example-data">{json_str}</script>',
            format='html'
        )
        container += json_node
        
        return [container]


def add_static_files(app: Sphinx, exception):
    """Write CSS and JS files when build finishes."""
    if exception is not None:
        return
    
    # Write CSS
    css_path = os.path.join(app.outdir, "_static", "rust_playground.css")
    os.makedirs(os.path.dirname(css_path), exist_ok=True)
    with open(css_path, "w") as f:
        f.write(get_css_content())
    
    # Write JS
    js_path = os.path.join(app.outdir, "_static", "rust_playground.js")
    with open(js_path, "w") as f:
        f.write(get_js_content())


def get_css_content() -> str:
    """Return the CSS content for rust playground styling."""
    return '''\
/* Rust Playground Interactive Examples */

/* Container */
.rust-example-container {
    position: relative;
    margin: 1em 0;
}

/* Badges row */
.rust-example-badges {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5em;
    margin-bottom: 0.5em;
}

.rust-example-badge {
    display: inline-block;
    padding: 0.2em 0.6em;
    font-family: monospace;
    font-size: 0.8em;
    font-weight: bold;
    border-radius: 3px;
    text-transform: lowercase;
}

.rust-example-badge-ignore {
    background-color: #6c757d;
    color: white;
}
.rust-example-badge-ignore::before { content: "⏭ "; }

.rust-example-badge-compile-fail {
    background-color: #dc3545;
    color: white;
}
.rust-example-badge-compile-fail::before { content: "✗ "; }

.rust-example-badge-should-panic {
    background-color: #fd7e14;
    color: white;
}
.rust-example-badge-should-panic::before { content: "💥 "; }

.rust-example-badge-no-run {
    background-color: #17a2b8;
    color: white;
}
.rust-example-badge-no-run::before { content: "⚙ "; }

.rust-example-badge-nightly {
    background-color: #6f42c1;
    color: white;
}
.rust-example-badge-nightly::before { content: "🌙 "; }

.rust-example-badge-version {
    background-color: #ffc107;
    color: #212529;
    cursor: help;
}

/* Miri badges */
.rust-example-badge-miri {
    background-color: #6f42c1;
    color: white;
}
.rust-example-badge-miri::before { content: "🔬 "; }

.rust-example-badge-miri-expect-ub {
    background-color: #b02a37;
    color: white;
}
.rust-example-badge-miri-expect-ub::before { content: "☣️ "; }

/* Button toolbar - injected by JavaScript */
.rust-example-buttons {
    position: absolute;
    top: 0.5em;
    right: 0.5em;
    display: flex;
    gap: 0.3em;
    opacity: 0;
    transition: opacity 0.2s ease;
    z-index: 10;
}

.rust-example-container:hover .rust-example-buttons {
    opacity: 1;
}

/* Adjust button position when badges are present */
.rust-example-container:has(.rust-example-badges) .rust-example-buttons {
    top: calc(0.5em + 1.8em + 0.5em);
}

/* Individual buttons */
.rust-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 4px;
    background-color: rgba(0, 0, 0, 0.3);
    color: #fff;
    cursor: pointer;
    transition: background-color 0.15s;
}

.rust-btn:hover {
    background-color: rgba(0, 0, 0, 0.5);
}

.rust-btn:disabled {
    opacity: 0.3;
    cursor: not-allowed;
}

.rust-btn-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 14px;
    height: 14px;
}

.rust-btn-icon svg {
    width: 100%;
    height: 100%;
    fill: currentColor;
}

/* Copy button tooltip */
.rust-btn-tooltip {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    padding: 0.3em 0.6em;
    margin-bottom: 0.3em;
    font-size: 0.75em;
    white-space: nowrap;
    background-color: #333;
    color: #fff;
    border-radius: 3px;
    opacity: 0;
    pointer-events: none;
    transition: opacity 0.2s;
}

.rust-btn-tooltip.show {
    opacity: 1;
}

/* Running state */
.rust-btn-run.running {
    opacity: 0.6;
    cursor: wait;
}

/* Hidden lines toggle active state */
.rust-btn-toggle-hidden.active {
    background-color: rgba(0, 0, 0, 0.6);
}

/* Hidden lines styling when revealed */
.rust-hidden-line {
    opacity: 0.5;
    background-color: rgba(128, 128, 128, 0.15);
}

/* Output area - injected by JavaScript */
.rust-example-output {
    margin-top: 0.5em;
    border: 1px solid #ddd;
    border-radius: 4px;
    background-color: #1e1e1e;
    overflow: hidden;
}

.rust-example-output-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5em 1em;
    background-color: #2d2d2d;
    border-bottom: 1px solid #444;
}

.rust-example-output-status {
    font-size: 0.85em;
    font-weight: bold;
}

.rust-example-output-status.success { color: #4caf50; }
.rust-example-output-status.success::before { content: "✓ "; }

.rust-example-output-status.error { color: #f44336; }
.rust-example-output-status.error::before { content: "✗ "; }

.rust-example-output-status.expected { color: #ff9800; }
.rust-example-output-status.expected::before { content: "✓ "; }

.rust-example-output-close {
    background: none;
    border: none;
    color: #aaa;
    font-size: 1.2em;
    cursor: pointer;
    padding: 0 0.3em;
}

.rust-example-output-close:hover {
    color: #fff;
}

.rust-example-output-content {
    margin: 0;
    padding: 1em;
    max-height: 300px;
    overflow: auto;
    font-family: monospace;
    font-size: 0.85em;
    color: #d4d4d4;
    white-space: pre-wrap;
    word-wrap: break-word;
}

/* Hide the JSON data script */
.rust-example-data {
    display: none !important;
}

/* Error notification */
.rust-example-error {
    background-color: #fff3cd;
    border: 1px solid #ffc107;
    border-radius: 4px;
    padding: 0.5em 1em;
    margin-top: 0.5em;
    display: flex;
    align-items: center;
    gap: 0.5em;
    font-size: 0.9em;
}

.rust-example-error-icon {
    font-size: 1.2em;
    flex-shrink: 0;
}

.rust-example-error-message {
    flex: 1;
    color: #856404;
}

.rust-example-error-retry {
    background-color: #0d6efd;
    color: white;
    border: none;
    border-radius: 3px;
    padding: 0.25em 0.75em;
    cursor: pointer;
    font-size: 0.85em;
}

.rust-example-error-retry:hover {
    background-color: #0b5ed7;
}

.rust-example-error-dismiss {
    background: transparent;
    border: none;
    font-size: 1.2em;
    cursor: pointer;
    color: #856404;
    padding: 0 0.25em;
}

.rust-example-error-dismiss:hover {
    color: #533f03;
}

/* Miri button styling */
.rust-btn-miri:hover {
    background-color: #6f42c1;
}

/* Miri-specific output status */
.rust-example-output-status.miri-success { color: #4caf50; }
.rust-example-output-status.miri-success::before { content: "🔬 "; }

.rust-example-output-status.miri-ub { color: #b02a37; }
.rust-example-output-status.miri-ub::before { content: "☣️ "; }
'''


def get_js_content() -> str:
    """Return the JavaScript content for rust playground interactivity."""
    return '''\
/* Rust Playground Interactive Examples */
(function() {
    'use strict';
    
    const PLAYGROUND_URL = 'https://play.rust-lang.org/execute';
    const PLAYGROUND_MIRI_URL = 'https://play.rust-lang.org/miri';
    
    // SVG icons (Font Awesome Free 6.2.0)
    const ICON_COPY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 448 512"><path d="M208 0H332.1c12.7 0 24.9 5.1 33.9 14.1l67.9 67.9c9 9 14.1 21.2 14.1 33.9V336c0 26.5-21.5 48-48 48H208c-26.5 0-48-21.5-48-48V48c0-26.5 21.5-48 48-48zM48 128h80v64H64V448H256V416h64v48c0 26.5-21.5 48-48 48H48c-26.5 0-48-21.5-48-48V176c0-26.5 21.5-48 48-48z"/></svg>';
    const ICON_PLAY = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 384 512"><path d="M73 39c-14.8-9.1-33.4-9.4-48.5-.9S0 62.6 0 80V432c0 17.4 9.4 33.4 24.5 41.9s33.7 8.1 48.5-.9L361 297c14.3-8.7 23-24.2 23-41s-8.7-32.2-23-41L73 39z"/></svg>';
    const ICON_EYE = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 576 512"><path d="M288 32c-80.8 0-145.5 36.8-192.6 80.6C48.6 156 17.3 208 2.5 243.7c-3.3 7.9-3.3 16.7 0 24.6C17.3 304 48.6 356 95.4 399.4C142.5 443.2 207.2 480 288 480s145.5-36.8 192.6-80.6c46.8-43.5 78.1-95.4 93-131.1c3.3-7.9 3.3-16.7 0-24.6c-14.9-35.7-46.2-87.7-93-131.1C433.5 68.8 368.8 32 288 32zM432 256c0 79.5-64.5 144-144 144s-144-64.5-144-144s64.5-144 144-144s144 64.5 144 144zM288 192c0 35.3-28.7 64-64 64c-11.5 0-22.3-3-31.6-8.4c-.2 2.8-.4 5.5-.4 8.4c0 53 43 96 96 96s96-43 96-96s-43-96-96-96c-2.8 0-5.6 .1-8.4 .4c5.3 9.3 8.4 20.1 8.4 31.6z"/></svg>';
    const ICON_MIRI = '🔬';  // Microscope emoji for Miri
    
    document.addEventListener('DOMContentLoaded', initializeRustExamples);
    
    function initializeRustExamples() {
        const containers = document.querySelectorAll('.rust-example-container');
        containers.forEach(initializeExample);
    }
    
    function initializeExample(container) {
        // Find the JSON data script
        const dataScript = container.querySelector('script.rust-example-data');
        if (!dataScript) {
            console.warn('No rust-example-data found in container', container);
            return;
        }
        
        let data;
        try {
            data = JSON.parse(dataScript.textContent);
        } catch (e) {
            console.error('Failed to parse rust example data:', e);
            return;
        }
        
        container._rustData = data;
        
        // Find the code block (Sphinx wraps it in div.highlight)
        const highlightDiv = container.querySelector('.highlight');
        if (!highlightDiv) {
            console.warn('No .highlight found in container', container);
            return;
        }
        
        // Make the highlight div position:relative for button positioning
        highlightDiv.style.position = 'relative';
        
        // Create and inject the button toolbar
        const buttons = createButtonToolbar(container, data);
        highlightDiv.appendChild(buttons);
        
        // Store reference to pre element for code manipulation
        container._preElement = highlightDiv.querySelector('pre');
        container._originalHTML = container._preElement ? container._preElement.innerHTML : '';
    }
    
    function createButtonToolbar(container, data) {
        const toolbar = document.createElement('div');
        toolbar.className = 'rust-example-buttons';
        
        // Copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'rust-btn rust-btn-copy';
        copyBtn.title = 'Copy to clipboard';
        copyBtn.setAttribute('aria-label', 'Copy to clipboard');
        copyBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_COPY + '</span><span class="rust-btn-tooltip"></span>';
        copyBtn.addEventListener('click', function() { handleCopy(container, data); });
        toolbar.appendChild(copyBtn);
        
        // Run button
        const runBtn = document.createElement('button');
        runBtn.className = 'rust-btn rust-btn-run';
        runBtn.title = data.runnable ? 'Run this code' : 'This example cannot be run';
        runBtn.setAttribute('aria-label', runBtn.title);
        runBtn.disabled = !data.runnable;
        runBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_PLAY + '</span>';
        if (data.runnable) {
            runBtn.addEventListener('click', function() { handleRun(container, data); });
        }
        toolbar.appendChild(runBtn);
        
        // Miri button (only if miri option is set and not skip)
        if (data.miri && data.miri.mode !== 'skip') {
            const miriBtn = document.createElement('button');
            miriBtn.className = 'rust-btn rust-btn-miri';
            miriBtn.title = 'Run with Miri (undefined behavior detector)';
            miriBtn.setAttribute('aria-label', miriBtn.title);
            miriBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_MIRI + '</span>';
            miriBtn.addEventListener('click', function() { handleMiri(container, data); });
            toolbar.appendChild(miriBtn);
        }
        
        // Toggle hidden lines button (only if there are hidden lines)
        if (data.hasHiddenLines) {
            const toggleBtn = document.createElement('button');
            toggleBtn.className = 'rust-btn rust-btn-toggle-hidden';
            toggleBtn.title = 'Show hidden lines';
            toggleBtn.setAttribute('aria-label', 'Show hidden lines');
            toggleBtn.innerHTML = '<span class="rust-btn-icon">' + ICON_EYE + '</span>';
            toggleBtn.addEventListener('click', function() { handleToggleHidden(container, data); });
            toolbar.appendChild(toggleBtn);
        }
        
        return toolbar;
    }
    
    function handleCopy(container, data) {
        const copyBtn = container.querySelector('.rust-btn-copy');
        const tooltip = copyBtn.querySelector('.rust-btn-tooltip');
        
        navigator.clipboard.writeText(data.code).then(function() {
            tooltip.textContent = 'Copied!';
            tooltip.classList.add('show');
            setTimeout(function() { tooltip.classList.remove('show'); }, 1500);
        }).catch(function(err) {
            console.error('Failed to copy:', err);
            tooltip.textContent = 'Failed';
            tooltip.classList.add('show');
            setTimeout(function() { tooltip.classList.remove('show'); }, 1500);
        });
    }
    
    function handleRun(container, data) {
        const runBtn = container.querySelector('.rust-btn-run');
        
        if (runBtn.classList.contains('running')) return;
        
        runBtn.classList.add('running');
        runBtn.disabled = true;
        
        // Store last action for retry
        container._lastAction = function() { handleRun(container, data); };
        
        // Remove any existing output or error
        const existingOutput = container.querySelector('.rust-example-output');
        if (existingOutput) existingOutput.remove();
        const existingError = container.querySelector('.rust-example-error');
        if (existingError) existingError.remove();
        
        // Create output area
        const output = createOutputArea();
        container.appendChild(output);
        
        const statusSpan = output.querySelector('.rust-example-output-status');
        const contentPre = output.querySelector('.rust-example-output-content');
        
        statusSpan.textContent = 'Running...';
        statusSpan.className = 'rust-example-output-status';
        
        fetch(PLAYGROUND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel: data.channel,
                mode: 'debug',
                edition: data.edition,
                crateType: 'bin',
                tests: false,
                code: data.code,
                backtrace: false
            })
        })
        .then(function(response) {
            if (!response.ok) {
                if (response.status === 429) {
                    throw new Error('rate_limit');
                }
                throw new Error('http_' + response.status);
            }
            return response.json();
        })
        .then(function(result) {
            displayResult(container, data, result, statusSpan, contentPre);
        })
        .catch(function(error) {
            output.remove();
            showError(container, error.message);
        })
        .finally(function() {
            runBtn.classList.remove('running');
            runBtn.disabled = false;
        });
    }
    
    function createOutputArea() {
        const output = document.createElement('div');
        output.className = 'rust-example-output';
        output.innerHTML = 
            '<div class="rust-example-output-header">' +
                '<span class="rust-example-output-status"></span>' +
                '<button class="rust-example-output-close" title="Close">×</button>' +
            '</div>' +
            '<pre class="rust-example-output-content"></pre>';
        
        output.querySelector('.rust-example-output-close').addEventListener('click', function() {
            output.remove();
        });
        
        return output;
    }
    
    function displayResult(container, data, result, statusSpan, contentPre) {
        const success = result.success;
        let output = '';
        
        if (result.stderr) output += result.stderr;
        if (result.stdout) {
            if (output) output += '\\n';
            output += result.stdout;
        }
        if (!output) output = success ? '(no output)' : '(compilation failed)';
        
        let statusText = '';
        let statusClass = '';
        
        switch (data.expectedOutcome) {
            case 'compile_fail':
                if (!success) {
                    statusText = data.expectedError && result.stderr && result.stderr.includes(data.expectedError)
                        ? 'Compilation failed as expected (' + data.expectedError + ')'
                        : 'Compilation failed as expected';
                    statusClass = 'expected';
                } else {
                    statusText = 'Unexpected success (expected compile_fail)';
                    statusClass = 'error';
                }
                break;
            case 'should_panic':
                if (success && ((result.stderr && result.stderr.includes('panicked')) || 
                               (result.stdout && result.stdout.includes('panicked')))) {
                    statusText = 'Panicked as expected';
                    statusClass = 'expected';
                } else if (!success) {
                    statusText = 'Compilation failed';
                    statusClass = 'error';
                } else {
                    statusText = 'Expected panic did not occur';
                    statusClass = 'error';
                }
                break;
            case 'no_run':
                if (success) {
                    statusText = 'Compiled successfully';
                    statusClass = 'success';
                    output = '(compilation successful - not executed)';
                } else {
                    statusText = 'Compilation failed';
                    statusClass = 'error';
                }
                break;
            default:
                statusText = success ? 'Success' : 'Failed';
                statusClass = success ? 'success' : 'error';
        }
        
        statusSpan.textContent = statusText;
        statusSpan.className = 'rust-example-output-status ' + statusClass;
        
        if (!success && data.expectedOutcome === 'success' && data.version) {
            output += '\\n\\nℹ️ Note: This example targets Rust ' + data.version + 
                     '. The playground uses the latest ' + data.channel + ' version.';
        }
        
        contentPre.textContent = output;
    }
    
    function handleMiri(container, data) {
        const miriBtn = container.querySelector('.rust-btn-miri');
        
        if (miriBtn.classList.contains('running')) return;
        
        miriBtn.classList.add('running');
        miriBtn.disabled = true;
        
        // Store last action for retry
        container._lastAction = function() { handleMiri(container, data); };
        
        // Remove any existing output or error
        const existingOutput = container.querySelector('.rust-example-output');
        if (existingOutput) existingOutput.remove();
        const existingError = container.querySelector('.rust-example-error');
        if (existingError) existingError.remove();
        
        // Create output area
        const output = createOutputArea();
        container.appendChild(output);
        
        const statusSpan = output.querySelector('.rust-example-output-status');
        const contentPre = output.querySelector('.rust-example-output-content');
        
        statusSpan.textContent = 'Running Miri...';
        statusSpan.className = 'rust-example-output-status';
        
        // Miri always uses nightly channel
        fetch(PLAYGROUND_MIRI_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                channel: 'nightly',  // Miri requires nightly
                edition: data.edition,
                code: data.code
            })
        })
        .then(function(response) {
            if (!response.ok) {
                if (response.status === 429) {
                    throw new Error('rate_limit');
                }
                throw new Error('http_' + response.status);
            }
            return response.json();
        })
        .then(function(result) {
            displayMiriResult(container, data, result, statusSpan, contentPre);
        })
        .catch(function(error) {
            output.remove();
            showError(container, error.message);
        })
        .finally(function() {
            miriBtn.classList.remove('running');
            miriBtn.disabled = false;
        });
    }
    
    function displayMiriResult(container, data, result, statusSpan, contentPre) {
        let output = '';
        
        if (result.stderr) output += result.stderr;
        if (result.stdout) {
            if (output) output += '\\n';
            output += result.stdout;
        }
        if (!output) output = '(no output from Miri)';
        
        // Check for UB in output
        const hasUB = output.includes('Undefined Behavior') || 
                      output.includes('error: unsupported operation') ||
                      output.includes('error[');
        
        const expectUB = data.miri && data.miri.mode === 'expect_ub';
        const success = expectUB ? hasUB : !hasUB;
        
        let statusText = '';
        let statusClass = '';
        
        if (success) {
            if (expectUB) {
                statusText = 'UB detected as expected';
                statusClass = 'miri-ub';
            } else {
                statusText = 'No undefined behavior detected';
                statusClass = 'miri-success';
            }
        } else {
            if (expectUB) {
                statusText = 'Expected UB but none detected';
                statusClass = 'error';
            } else {
                statusText = 'Undefined behavior detected!';
                statusClass = 'miri-ub';
            }
        }
        
        statusSpan.textContent = statusText;
        statusSpan.className = 'rust-example-output-status ' + statusClass;
        contentPre.textContent = output;
    }
    
    function showError(container, errorType) {
        // Remove any existing error
        const existing = container.querySelector('.rust-example-error');
        if (existing) existing.remove();
        
        // Determine error message
        let message = 'Playground unavailable';
        if (errorType === 'rate_limit') {
            message = 'Too many requests - wait a moment';
        } else if (errorType && errorType.startsWith('http_5')) {
            message = 'Playground error - try again';
        } else if (errorType === 'timeout') {
            message = 'Request timed out';
        }
        
        const errorDiv = document.createElement('div');
        errorDiv.className = 'rust-example-error';
        errorDiv.innerHTML = 
            '<span class="rust-example-error-icon">⚠️</span>' +
            '<span class="rust-example-error-message">' + message + '</span>' +
            '<button class="rust-example-error-retry">Retry</button>' +
            '<button class="rust-example-error-dismiss">×</button>';
        
        // Wire up buttons
        errorDiv.querySelector('.rust-example-error-retry').addEventListener('click', function() {
            errorDiv.remove();
            if (container._lastAction) container._lastAction();
        });
        errorDiv.querySelector('.rust-example-error-dismiss').addEventListener('click', function() {
            errorDiv.remove();
        });
        
        // Auto-dismiss after 10 seconds
        setTimeout(function() {
            if (errorDiv.parentNode) errorDiv.remove();
        }, 10000);
        
        container.appendChild(errorDiv);
    }
    
    function handleToggleHidden(container, data) {
        const toggleBtn = container.querySelector('.rust-btn-toggle-hidden');
        const pre = container._preElement;
        if (!pre) return;
        
        const isShowingHidden = toggleBtn.classList.contains('active');
        
        if (isShowingHidden) {
            // Restore original Pygments-highlighted HTML (without hidden lines)
            pre.innerHTML = container._originalHTML;
            toggleBtn.classList.remove('active');
            toggleBtn.title = 'Show hidden lines';
            toggleBtn.setAttribute('aria-label', 'Show hidden lines');
        } else {
            // Show pre-highlighted full code with hidden lines marked
            // This HTML was generated at build time by Pygments
            if (data.fullCodeHighlighted) {
                pre.innerHTML = data.fullCodeHighlighted;
            }
            toggleBtn.classList.add('active');
            toggleBtn.title = 'Hide hidden lines';
            toggleBtn.setAttribute('aria-label', 'Hide hidden lines');
        }
    }
    
    window.RustPlayground = {
        initialize: initializeRustExamples
    };
})();
'''


def check_miri_violations(app, env):
    """
    Check for miri violations after all documents are read.
    Raises MiriValidationError if any unsafe code lacks :miri: option.
    
    This scans all doctrees at consistency-check time rather than storing
    data during directive processing, ensuring parallel builds work correctly.
    """
    # Check if miri enforcement is enabled
    config_path = Path(app.confdir) / "rust_examples_config.toml"
    try:
        config = RustExamplesConfig.load(config_path)
    except FileNotFoundError:
        config = RustExamplesConfig()
    
    require_miri = getattr(app.config, 'rust_examples_require_miri_for_unsafe', 
                           config.miri_require_for_unsafe)
    
    if not require_miri:
        return
    
    violations = []
    
    # Iterate over all doctrees
    docnames = list(env.all_docs.keys())
    pbar = get_tqdm(
        iterable=docnames,
        desc="Checking unsafe code for :miri:",
        bar_format=bar_format,
        unit="doc",
    )
    
    for docname in pbar:
        try:
            doctree = env.get_doctree(docname)
        except Exception:
            continue
        
        # Find all rust-example code blocks
        for node in doctree.traverse(nodes.literal_block):
            if node.get('language') != 'rust':
                continue
            if 'rust-example-code' not in node.get('classes', []):
                continue
            
            # Check if this code has unsafe and no miri option
            full_code = node.get('rustdoc_full_code', '')
            miri_mode = node.get('rustdoc_miri_mode')
            
            if full_code and contains_unsafe_keyword(full_code) and miri_mode is None:
                source = node.get('source', docname)
                line = node.get('line', 0)
                violations.append(f"{source}:{line}")
    
    pbar.close()
    
    if violations:
        error_msg = (
            f"{len(violations)} example(s) contain `unsafe` code without :miri: option:\n\n"
        )
        for loc in violations:
            error_msg += f"  • {loc}\n"
        error_msg += (
            "\nFor each example, add one of:\n"
            "  :miri:           - Run Miri to verify no undefined behavior\n"
            "  :miri: expect_ub - This example intentionally demonstrates UB\n"
            "  :miri: skip      - Skip Miri check (document why in prose)\n\n"
            "See docs/INTERACTIVE_RUST_EXAMPLES.md for guidance.\n"
            "To disable this check, set rust_examples_require_miri_for_unsafe = False in conf.py"
        )
        logger.error(error_msg)
        app.builder.statuscode = 1
        raise MiriValidationError(error_msg)


def setup(app: Sphinx):
    """Setup the rust-example extension."""
    
    app.add_directive('rust-example', RustExampleDirective)
    
    app.add_config_value('rust_examples_show_hidden', False, 'env')
    app.add_config_value('rust_examples_prelude_file', None, 'env')
    
    # Miri configuration
    app.add_config_value('rust_examples_require_miri_for_unsafe', True, 'env')
    app.add_config_value('rust_examples_miri_timeout', 60, 'env')
    
    # Register static files
    app.add_css_file('rust_playground.css')
    app.add_js_file('rust_playground.js')
    
    # Write files on build finish
    app.connect('build-finished', add_static_files)
    
    # Check for miri violations after documents are read
    app.connect('env-check-consistency', check_miri_violations)
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
    }
