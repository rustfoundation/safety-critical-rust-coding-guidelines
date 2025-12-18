# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Sphinx extension for validating bibliography entries in coding guidelines.

This extension provides:
1. URL validity checking - verifies that all URLs in bibliography entries are accessible
2. Duplicate URL detection - warns when the same URL appears in multiple guidelines
3. Citation key validation - ensures citation keys follow the required format
4. Citation reference checking - verifies that referenced citations exist

Configuration options (in conf.py):
    bibliography_check_urls = True       # Enable URL validation
    bibliography_url_timeout = 10        # Timeout in seconds for URL checks
    bibliography_fail_on_broken = True   # Error vs warning for broken URLs
    bibliography_fail_on_duplicates = True  # Error vs warning for duplicate URLs
"""

import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Set, Tuple
from urllib.parse import urlparse

import requests
from sphinx.application import Sphinx
from sphinx.errors import SphinxError
from sphinx_needs.data import SphinxNeedsData

from .common import bar_format, get_tqdm, logger

# Citation key pattern: [UPPERCASE-WITH-HYPHENS] or [UPPERCASE-WITH-HYPHENS-AND-NUMBERS-123]
CITATION_KEY_PATTERN = re.compile(r'^\[([A-Z][A-Z0-9-]*[A-Z0-9])\]$')

# Pattern to find citation keys in text
CITATION_REF_PATTERN = re.compile(r'\[([A-Z][A-Z0-9-]*[A-Z0-9])\]')

# URL pattern for extraction from bibliography content
URL_PATTERN = re.compile(r'https?://[^\s<>"\')\]]+')


class BibliographyValidationError(SphinxError):
    category = "Bibliography Validation Error"


def validate_citation_key_format(key: str) -> Tuple[bool, str]:
    """
    Validate that a citation key follows the required format.
    
    Format: [UPPERCASE-WITH-HYPHENS]
    - Must start with uppercase letter
    - Can contain uppercase letters, numbers, and hyphens
    - Must end with uppercase letter or number
    - Maximum length: 50 characters
    
    Args:
        key: The citation key to validate (including brackets)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not key:
        return False, "Citation key is empty"
    
    if len(key) > 52:  # 50 chars + 2 brackets
        return False, f"Citation key '{key}' exceeds maximum length of 50 characters"
    
    if not CITATION_KEY_PATTERN.match(key):
        return False, (
            f"Citation key '{key}' does not follow required format. "
            "Expected: [UPPERCASE-WITH-HYPHENS] (e.g., [RUST-REF-UNION], [CERT-C-INT34])"
        )
    
    return True, ""


def extract_urls_from_content(content: str) -> List[str]:
    """
    Extract all URLs from bibliography content.
    
    Args:
        content: The bibliography content text
        
    Returns:
        List of URLs found in the content
    """
    return URL_PATTERN.findall(content)


def extract_citation_keys_from_content(content: str) -> List[str]:
    """
    Extract all citation key definitions from bibliography content.
    
    Looks for patterns like:
    - .. [CITATION-KEY]
    - [CITATION-KEY] at the start of a line in a list-table
    
    Args:
        content: The bibliography content text
        
    Returns:
        List of citation keys found
    """
    keys = []
    
    # Pattern for RST citation definition: .. [KEY]
    rst_citation = re.compile(r'^\s*\.\.\s+(\[[A-Z][A-Z0-9-]*[A-Z0-9]\])', re.MULTILINE)
    for match in rst_citation.finditer(content):
        keys.append(match.group(1))
    
    # Pattern for list-table style: * - .. [KEY]
    list_table_citation = re.compile(r'^\s*\*\s+-\s+\.\.\s+(\[[A-Z][A-Z0-9-]*[A-Z0-9]\])', re.MULTILINE)
    for match in list_table_citation.finditer(content):
        keys.append(match.group(1))
    
    return keys


def extract_citation_references(content: str) -> List[str]:
    """
    Extract all citation references from guideline content.
    
    Looks for [CITATION-KEY] patterns in the text that are references
    to bibliography entries.
    
    Args:
        content: The guideline or rationale content
        
    Returns:
        List of citation references found
    """
    return CITATION_REF_PATTERN.findall(content)


def check_url_validity(url: str, timeout: int = 10) -> Tuple[bool, str, int]:
    """
    Check if a URL is valid and accessible.
    
    Args:
        url: The URL to check
        timeout: Request timeout in seconds
        
    Returns:
        Tuple of (is_valid, error_message, status_code)
    """
    try:
        # Parse URL to validate format
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False, "Invalid URL format", 0
        
        # Try HEAD request first (faster)
        response = requests.head(
            url,
            timeout=timeout,
            allow_redirects=True,
            headers={'User-Agent': 'Mozilla/5.0 (compatible; BibliographyValidator/1.0)'}
        )
        
        # Some servers don't support HEAD, try GET
        if response.status_code == 405:
            response = requests.get(
                url,
                timeout=timeout,
                allow_redirects=True,
                stream=True,  # Don't download full content
                headers={'User-Agent': 'Mozilla/5.0 (compatible; BibliographyValidator/1.0)'}
            )
        
        if response.status_code >= 400:
            return False, f"HTTP {response.status_code}", response.status_code
        
        return True, "", response.status_code
        
    except requests.exceptions.Timeout:
        return False, "Request timed out", 0
    except requests.exceptions.SSLError as e:
        return False, f"SSL error: {str(e)[:50]}", 0
    except requests.exceptions.ConnectionError as e:
        return False, f"Connection error: {str(e)[:50]}", 0
    except requests.exceptions.RequestException as e:
        return False, f"Request error: {str(e)[:50]}", 0
    except Exception as e:
        return False, f"Unexpected error: {str(e)[:50]}", 0


def check_urls_parallel(
    urls: List[Tuple[str, str, str]],  # (url, guideline_id, source_file)
    timeout: int = 10,
    max_workers: int = 5
) -> List[Dict]:
    """
    Check multiple URLs in parallel.
    
    Args:
        urls: List of (url, guideline_id, source_file) tuples
        timeout: Request timeout in seconds
        max_workers: Maximum number of parallel workers
        
    Returns:
        List of result dictionaries with url, guideline_id, source_file, is_valid, error_message
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {
            executor.submit(check_url_validity, url, timeout): (url, gid, src)
            for url, gid, src in urls
        }
        
        for future in as_completed(future_to_url):
            url, guideline_id, source_file = future_to_url[future]
            try:
                is_valid, error_message, status_code = future.result()
                results.append({
                    'url': url,
                    'guideline_id': guideline_id,
                    'source_file': source_file,
                    'is_valid': is_valid,
                    'error_message': error_message,
                    'status_code': status_code,
                })
            except Exception as e:
                results.append({
                    'url': url,
                    'guideline_id': guideline_id,
                    'source_file': source_file,
                    'is_valid': False,
                    'error_message': f"Check failed: {str(e)[:50]}",
                    'status_code': 0,
                })
    
    return results


def validate_bibliography(app: Sphinx, env) -> None:
    """
    Main validation function for bibliography entries.
    
    This function:
    1. Collects all bibliography entries from guidelines
    2. Validates citation key formats
    3. Checks for duplicate URLs across guidelines
    4. Optionally validates URL accessibility
    5. Checks that citation references match definitions
    
    Args:
        app: The Sphinx application
        env: The Sphinx environment
    """
    if not app.config.bibliography_check_urls:
        logger.info("Bibliography URL validation disabled")
        return
    
    logger.info("Validating bibliography entries...")
    
    data = SphinxNeedsData(env)
    all_needs = data.get_needs_view()
    
    # Collect data for validation
    all_urls: List[Tuple[str, str, str]] = []  # (url, guideline_id, source_file)
    url_to_guidelines: Dict[str, List[str]] = defaultdict(list)
    citation_definitions: Dict[str, List[str]] = defaultdict(list)  # key -> [guideline_ids]
    citation_references: Dict[str, Set[str]] = defaultdict(set)  # guideline_id -> {referenced_keys}
    
    errors = []
    warnings = []
    
    # First pass: collect guidelines and their bibliographies
    guidelines = {k: v for k, v in all_needs.items() if v.get("type") == "guideline"}
    
    pbar = get_tqdm(
        iterable=guidelines.items(),
        desc="Collecting bibliography data",
        bar_format=bar_format,
        unit="guideline",
    )
    
    for guideline_id, guideline in pbar:
        pbar.set_postfix(guideline=guideline_id[:20])
        source_file = guideline.get("docname", "unknown")
        
        # Check for bibliography children
        parent_needs_back = guideline.get("parent_needs_back", [])
        
        for child_id in parent_needs_back:
            if child_id in all_needs:
                child = all_needs[child_id]
                
                if child.get("type") == "bibliography":
                    bib_content = child.get("content", "")
                    
                    # Extract and validate citation keys
                    keys = extract_citation_keys_from_content(bib_content)
                    for key in keys:
                        is_valid, error_msg = validate_citation_key_format(key)
                        if not is_valid:
                            errors.append(f"{source_file}: {error_msg}")
                        else:
                            # Track which guidelines define this key
                            citation_definitions[key].append(guideline_id)
                    
                    # Extract URLs
                    urls = extract_urls_from_content(bib_content)
                    for url in urls:
                        all_urls.append((url, guideline_id, source_file))
                        url_to_guidelines[url].append(guideline_id)
        
        # Collect citation references from guideline content and rationale
        guideline_content = guideline.get("content", "")
        refs = extract_citation_references(guideline_content)
        for ref in refs:
            citation_references[guideline_id].add(f"[{ref}]")
    
    pbar.close()
    
    # Check for duplicate URLs
    logger.info("Checking for duplicate URLs...")
    for url, guideline_ids in url_to_guidelines.items():
        if len(guideline_ids) > 1:
            msg = (
                f"Duplicate URL detected:\n"
                f"  URL: {url}\n"
                f"  Found in: {', '.join(guideline_ids)}\n"
                f"  Action: Consider if both guidelines need this reference"
            )
            if app.config.bibliography_fail_on_duplicates:
                errors.append(msg)
            else:
                warnings.append(msg)
    
    # Validate URLs if enabled
    if all_urls:
        logger.info(f"Validating {len(all_urls)} URLs...")
        
        # Deduplicate URLs for checking
        unique_urls = {}
        for url, gid, src in all_urls:
            if url not in unique_urls:
                unique_urls[url] = (url, gid, src)
        
        url_results = check_urls_parallel(
            list(unique_urls.values()),
            timeout=app.config.bibliography_url_timeout,
            max_workers=5
        )
        
        for result in url_results:
            if not result['is_valid']:
                msg = (
                    f"Broken URL in {result['source_file']}:\n"
                    f"  URL: {result['url']}\n"
                    f"  Guideline: {result['guideline_id']}\n"
                    f"  Error: {result['error_message']}\n"
                    f"  Action: Update or remove this reference"
                )
                if app.config.bibliography_fail_on_broken:
                    errors.append(msg)
                else:
                    warnings.append(msg)
    
    # Check for undefined citation references
    logger.info("Checking citation references...")
    all_defined_keys = set(citation_definitions.keys())
    
    for guideline_id, refs in citation_references.items():
        for ref in refs:
            if ref not in all_defined_keys:
                # Check if it might be defined in the same guideline's bibliography
                guideline = guidelines.get(guideline_id)
                if guideline:
                    parent_needs_back = guideline.get("parent_needs_back", [])
                    found_in_own_bib = False
                    for child_id in parent_needs_back:
                        if child_id in all_needs and all_needs[child_id].get("type") == "bibliography":
                            bib_content = all_needs[child_id].get("content", "")
                            if ref in bib_content:
                                found_in_own_bib = True
                                break
                    
                    if not found_in_own_bib:
                        source_file = guideline.get("docname", "unknown")
                        warnings.append(
                            f"Undefined citation reference in {source_file}:\n"
                            f"  Reference: {ref}\n"
                            f"  Guideline: {guideline_id}\n"
                            f"  Action: Add this citation to the bibliography or remove the reference"
                        )
    
    # Check for unused citations
    for key, guideline_ids in citation_definitions.items():
        for gid in guideline_ids:
            if key not in citation_references.get(gid, set()):
                guideline = guidelines.get(gid)
                if guideline:
                    source_file = guideline.get("docname", "unknown")
                    warnings.append(
                        f"Unused citation in {source_file}:\n"
                        f"  Citation: {key}\n"
                        f"  Guideline: {gid}\n"
                        f"  Action: Reference this citation in the guideline or remove it"
                    )
    
    # Report warnings
    for warning in warnings:
        logger.warning(f"[bibliography_validator] {warning}")
    
    # Report errors and potentially fail build
    if errors:
        error_message = "Bibliography validation failed:\n\n"
        for error in errors:
            error_message += f"ERROR: {error}\n\n"
        logger.error(error_message)
        raise BibliographyValidationError(error_message)
    
    logger.info("Bibliography validation complete")


def setup(app: Sphinx):
    """Setup the bibliography validator extension."""
    
    # Configuration values
    app.add_config_value('bibliography_check_urls', False, 'env')
    app.add_config_value('bibliography_url_timeout', 10, 'env')
    app.add_config_value('bibliography_fail_on_broken', True, 'env')
    app.add_config_value('bibliography_fail_on_duplicates', True, 'env')
    
    # Connect to the consistency check phase
    app.connect("env-check-consistency", validate_bibliography)
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
    }
