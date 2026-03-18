# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Sphinx extension for validating text content in coding guidelines.

This extension provides general text validation checks including:
1. Inline URL detection - ensures URLs use proper bibliography or :std: role references
2. (Future) Other text quality checks

Configuration options (in conf.py):
    text_check_inline_urls = True           # Enable inline URL detection
    text_check_fail_on_inline_urls = True   # Error vs warning for inline URLs
"""

import re
from typing import List, Tuple

from sphinx.application import Sphinx
from sphinx.errors import SphinxError
from sphinx_needs.data import SphinxNeedsData

from .common import bar_format, get_tqdm, logger

# Pattern to detect inline URLs in RST text
# Matches both:
#   - Bare URLs: https://example.com
#   - RST link syntax: `link text <https://example.com>`_
INLINE_URL_PATTERN = re.compile(
    r'(?:'
    r'`[^`]+<(https?://[^>]+)>`_'  # RST link syntax with URL capture
    r'|'
    r'(?<![`<])(https?://[^\s\]>`\'\"]+)'  # Bare URLs (not inside RST link or role)
    r')'
)

# Pattern to detect URLs that are already inside proper roles
# These should NOT be flagged as errors
ROLE_URL_PATTERN = re.compile(
    r':(?:std|cite|bibentry|ref|doc):`[^`]*`'
)

# Pattern to detect bibliography table content (URLs here are expected)
BIBLIOGRAPHY_CONTEXT_PATTERN = re.compile(
    r'^\s*-\s+.*https?://',  # Table row with URL (bibliography entries)
    re.MULTILINE
)

# URLs that should use the :std: role
STD_URL_PATTERNS = [
    re.compile(r'https?://doc\.rust-lang\.org/(?:stable/)?(?:std|core|alloc)/'),
    re.compile(r'https?://doc\.rust-lang\.org/(?:stable/)?(?:nightly/)?(?:std|core|alloc)/'),
]

# URLs that are allowed inline (e.g., FLS links that get converted to citations)
# These will still be flagged but with different guidance
FLS_URL_PATTERN = re.compile(r'https?://rust-lang\.github\.io/fls/')


class TextValidationError(SphinxError):
    category = "Text Validation Error"


def is_std_url(url: str) -> bool:
    """Check if a URL points to Rust standard library documentation."""
    return any(pattern.match(url) for pattern in STD_URL_PATTERNS)


def is_fls_url(url: str) -> bool:
    """Check if a URL points to the Ferrocene Language Specification."""
    return bool(FLS_URL_PATTERN.match(url))


def extract_std_path(url: str) -> str:
    """
    Extract the suggested :std: role path from a std/core/alloc URL.
    
    Examples:
        https://doc.rust-lang.org/std/num/struct.Wrapping.html -> std::num::Wrapping
        https://doc.rust-lang.org/core/primitive.u32.html#method.checked_shl -> u32::checked_shl
    """
    # Remove the base URL
    path = re.sub(r'https?://doc\.rust-lang\.org/(?:stable/)?(?:nightly/)?', '', url)
    
    # Remove .html extension and fragment
    path = re.sub(r'\.html.*$', '', path)
    
    # Handle primitive types specially
    if '/primitive.' in path:
        # core/primitive.u32 -> u32
        match = re.search(r'primitive\.(\w+)', path)
        if match:
            prim_type = match.group(1)
            # Check for method fragment
            method_match = re.search(r'#method\.(\w+)', url)
            if method_match:
                return f"{prim_type}::{method_match.group(1)}"
            return prim_type
    
    # Handle struct/enum/trait types
    # std/num/struct.Wrapping -> std::num::Wrapping
    path = re.sub(r'/(?:struct|enum|trait|fn|type|constant|macro)\.', '::', path)
    
    # Convert remaining slashes to ::
    path = path.replace('/', '::')
    
    # Handle method fragments
    method_match = re.search(r'#method\.(\w+)', url)
    if method_match:
        path = f"{path}::{method_match.group(1)}"
    
    return path


def find_inline_urls(content: str, source_context: str = "") -> List[Tuple[str, int, str]]:
    """
    Find inline URLs in content that should use proper roles.
    
    Args:
        content: The text content to check
        source_context: Context string for error messages
        
    Returns:
        List of (url, line_number, suggestion) tuples
    """
    issues = []
    
    # Split into lines for line number tracking
    lines = content.split('\n')
    
    # Track which lines are inside bibliography tables
    in_bibliography = False
    bibliography_indent = 0
    
    for line_num, line in enumerate(lines, start=1):
        # Check if we're entering/exiting a bibliography section
        if '.. list-table::' in line and 'bibliography' in content[:content.find(line)].lower():
            in_bibliography = True
            bibliography_indent = len(line) - len(line.lstrip())
            continue
        
        # If we're in a bibliography and hit a line with less indentation, we're out
        if in_bibliography:
            stripped = line.lstrip()
            if stripped and not stripped.startswith('-') and not stripped.startswith('*'):
                current_indent = len(line) - len(stripped)
                if current_indent <= bibliography_indent and not line.strip().startswith(':'):
                    in_bibliography = False
        
        # Skip lines that are part of bibliography tables
        if in_bibliography:
            continue
        
        # Skip lines that are comments
        if line.strip().startswith('..') and '::' not in line:
            continue
            
        # Skip lines that contain role definitions (like :bibentry: lines)
        if ':bibentry:`' in line or ':cite:`' in line:
            continue
        
        # Find all URLs in this line
        for match in INLINE_URL_PATTERN.finditer(line):
            # Get the URL (from either capture group)
            url = match.group(1) or match.group(2)
            if not url:
                continue
            
            # Skip if this URL is inside a proper role (check surrounding context)
            # This is a simplified check - we look for role patterns nearby
            start_pos = match.start()
            prefix = line[:start_pos]
            
            # Skip if preceded by a backtick (likely inside a role)
            if prefix.rstrip().endswith('`'):
                continue
                
            # Determine the suggestion based on URL type
            if is_std_url(url):
                std_path = extract_std_path(url)
                suggestion = f"Use :std:`{std_path}` role instead"
            elif is_fls_url(url):
                suggestion = "Add to bibliography and use :cite:`gui_ID:KEY` role"
            else:
                suggestion = "Add to bibliography and use :cite:`gui_ID:KEY` role"
            
            issues.append((url, line_num, suggestion))
    
    return issues


def check_inline_urls(app: Sphinx, env) -> None:
    """
    Check for inline URLs in guideline content.
    
    This function scans all guideline content for inline URLs that should
    instead use proper bibliography citations or :std: roles.
    
    Args:
        app: The Sphinx application
        env: The Sphinx environment
    """
    if not app.config.text_check_inline_urls:
        logger.info("Inline URL checking disabled")
        return
    
    logger.info("Checking for inline URLs in guidelines...")
    
    data = SphinxNeedsData(env)
    all_needs = data.get_needs_view()
    
    errors = []
    warnings = []
    
    # Get all guidelines
    guidelines = {k: v for k, v in all_needs.items() if v.get("type") == "guideline"}
    
    if not guidelines:
        logger.info("No guidelines found, skipping inline URL check")
        return
    
    pbar = get_tqdm(
        iterable=guidelines.items(),
        desc="Checking for inline URLs",
        bar_format=bar_format,
        unit="guideline",
    )
    
    for guideline_id, guideline in pbar:
        pbar.set_postfix(guideline=guideline_id[:20])
        source_file = guideline.get("docname", "unknown")
        
        # Check guideline content
        content = guideline.get("content", "")
        issues = find_inline_urls(content, f"guideline {guideline_id}")
        
        for url, line_num, suggestion in issues:
            msg = format_inline_url_error(
                url=url,
                guideline_id=guideline_id,
                source_file=source_file,
                section="content",
                suggestion=suggestion
            )
            if app.config.text_check_fail_on_inline_urls:
                errors.append(msg)
            else:
                warnings.append(msg)
        
        # Check child needs (rationale, examples, etc.)
        parent_needs_back = guideline.get("parent_needs_back", [])
        for child_id in parent_needs_back:
            if child_id in all_needs:
                child = all_needs[child_id]
                child_type = child.get("type", "unknown")
                
                # Skip bibliography - URLs are expected there
                if child_type == "bibliography":
                    continue
                
                child_content = child.get("content", "")
                child_issues = find_inline_urls(child_content, f"{child_type} {child_id}")
                
                for url, line_num, suggestion in child_issues:
                    msg = format_inline_url_error(
                        url=url,
                        guideline_id=guideline_id,
                        source_file=source_file,
                        section=child_type,
                        suggestion=suggestion
                    )
                    if app.config.text_check_fail_on_inline_urls:
                        errors.append(msg)
                    else:
                        warnings.append(msg)
    
    pbar.close()
    
    # Report warnings
    for warning in warnings:
        logger.warning(f"[text_checks] {warning}")
    
    # Report errors and fail build
    if errors:
        error_message = "Text validation failed - inline URLs detected:\n\n"
        error_message += "Inline URLs should not be used in guideline text.\n"
        error_message += "Instead, use one of the following approaches:\n\n"
        error_message += "  1. For Rust standard library links:\n"
        error_message += "     Use the :std: role, e.g., :std:`std::num::Wrapping`\n\n"
        error_message += "  2. For external references:\n"
        error_message += "     Add to the guideline's bibliography section and use :cite:`gui_ID:KEY`\n\n"
        error_message += "Detected issues:\n\n"
        
        for error in errors:
            error_message += f"ERROR: {error}\n\n"
        
        logger.error(error_message)
        raise TextValidationError(error_message)
    
    logger.info("Inline URL check complete")


def format_inline_url_error(
    url: str,
    guideline_id: str,
    source_file: str,
    section: str,
    suggestion: str
) -> str:
    """Format an error message for an inline URL."""
    return (
        f"Inline URL in {source_file} ({section}):\n"
        f"  Guideline: {guideline_id}\n"
        f"  URL: {url}\n"
        f"  Fix: {suggestion}"
    )


def setup(app: Sphinx):
    """Setup the text checks extension."""
    
    # Configuration values
    app.add_config_value('text_check_inline_urls', True, 'env')
    app.add_config_value('text_check_fail_on_inline_urls', True, 'env')
    
    # Connect to the consistency check phase
    app.connect("env-check-consistency", check_inline_urls)
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
    }
