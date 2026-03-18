# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Sphinx extension for validating bibliography entries in coding guidelines.

This extension provides:
1. URL validity checking - verifies that all URLs in bibliography entries are accessible
2. Duplicate URL consistency - ensures same URLs use identical citation keys and descriptions
3. Citation key validation - ensures citation keys follow the required format
4. Citation reference checking - verifies that referenced citations exist

Configuration options (in conf.py):
    bibliography_check_urls = True       # Enable URL validation
    bibliography_url_timeout = 10        # Timeout in seconds for URL checks
    bibliography_fail_on_broken = True   # Error vs warning for broken URLs
    bibliography_fail_on_inconsistent = True  # Error vs warning for inconsistent duplicate URLs
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

# Citation key pattern for validation: UPPERCASE-WITH-HYPHENS
# Used to validate keys after extraction
VALID_CITATION_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9-]*[A-Z0-9]$')

# Pattern to find :cite: role references in text
# Format: :cite:`gui_XxxYyyZzz:CITATION-KEY`
# Permissive pattern to capture potentially invalid keys for validation
CITE_ROLE_PATTERN = re.compile(r':cite:`(gui_[a-zA-Z0-9]+):([^`]+)`')

# Pattern to find :bibentry: role definitions in bibliography
# Format: :bibentry:`gui_XxxYyyZzz:CITATION-KEY`
# Permissive pattern to capture potentially invalid keys for validation
BIBENTRY_ROLE_PATTERN = re.compile(r':bibentry:`(gui_[a-zA-Z0-9]+):([^`]+)`')

# Legacy pattern for plain text [KEY] format (for backwards compatibility)
# This one stays strict since we only want to match valid-looking legacy refs
PLAIN_CITATION_REF_PATTERN = re.compile(r'\[([A-Z][A-Z0-9-]*[A-Z0-9])\]')

# URL pattern for extraction from bibliography content
URL_PATTERN = re.compile(r'https?://[^\s<>"\')\]]+')


class BibliographyValidationError(SphinxError):
    category = "Bibliography Validation Error"


def suggest_citation_key(invalid_key: str) -> str:
    """
    Suggest a valid citation key based on an invalid one.
    
    Transforms the key by:
    - Converting to uppercase
    - Replacing spaces and underscores with hyphens
    - Removing invalid characters
    - Ensuring it starts with a letter
    - Ensuring it ends with a letter or number
    
    Args:
        invalid_key: The invalid citation key
        
    Returns:
        A suggested valid citation key
    """
    # Start with uppercase
    suggested = invalid_key.upper()
    
    # Replace spaces and underscores with hyphens
    suggested = re.sub(r'[\s_]+', '-', suggested)
    
    # Remove invalid characters (keep only A-Z, 0-9, and hyphens)
    suggested = re.sub(r'[^A-Z0-9-]', '', suggested)
    
    # Remove leading/trailing hyphens
    suggested = suggested.strip('-')
    
    # Collapse multiple hyphens
    suggested = re.sub(r'-+', '-', suggested)
    
    # Ensure it starts with a letter
    if suggested and not suggested[0].isalpha():
        suggested = 'REF-' + suggested
    
    # Ensure it ends with a letter or number (not a hyphen)
    if suggested and suggested[-1] == '-':
        suggested = suggested[:-1]
    
    # Handle empty or too short result
    if len(suggested) < 2:
        suggested = 'REF-CITATION'
    
    return suggested


def validate_citation_key_format(key: str) -> Tuple[bool, str]:
    """
    Validate that a citation key follows the required format.
    
    Format: UPPERCASE-WITH-HYPHENS (without brackets for the raw key)
    - Must start with uppercase letter
    - Can contain uppercase letters, numbers, and hyphens
    - Must end with uppercase letter or number
    - Maximum length: 50 characters
    
    Args:
        key: The citation key to validate (with or without brackets)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not key:
        return False, "Citation key is empty"
    
    # Remove brackets if present
    clean_key = key.strip('[]')
    
    if len(clean_key) > 50:
        return False, "Exceeds maximum length of 50 characters"
    
    # Check format using the defined pattern
    if not VALID_CITATION_KEY_PATTERN.match(clean_key):
        return False, "Must be UPPERCASE-WITH-HYPHENS (e.g., RUST-REF-UNION)"
    
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


def extract_bibliography_entries(content: str) -> List[Dict[str, str]]:
    """
    Extract complete bibliography entries from content.
    
    Each entry contains:
    - citation_key: The citation key (e.g., "RUST-REF-UNION")
    - description: The description text (author, title, etc.)
    - url: The URL if present
    
    Args:
        content: The bibliography content text
        
    Returns:
        List of dicts with citation_key, description, and url
    """
    entries = []
    
    # Pattern to match bibliography table rows:
    # * - :bibentry:`gui_ID:CITATION-KEY`
    #   - Description text. https://url.example.com
    #
    # We need to match across lines, capturing:
    # 1. The citation key from :bibentry:
    # 2. The description and URL from the next line
    
    # First, find all :bibentry: roles and their positions
    # Use permissive pattern to capture potentially invalid keys
    bibentry_pattern = re.compile(
        r':bibentry:`gui_[a-zA-Z0-9]+:([^`]+)`'
    )
    
    # Split content into lines for processing
    lines = content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i]
        match = bibentry_pattern.search(line)
        
        if match:
            citation_key = match.group(1)
            
            # Look for the description in the next line(s)
            description = ""
            url = ""
            
            # The description is typically on the next line starting with "- " or "  -"
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                
                # Check if this is the description line (starts with "- " after stripping)
                if next_line.startswith('- '):
                    desc_content = next_line[2:].strip()  # Remove "- " prefix
                    
                    # Extract URL from description if present
                    url_match = URL_PATTERN.search(desc_content)
                    if url_match:
                        url = url_match.group(0)
                        # Description is everything before the URL
                        description = desc_content[:url_match.start()].strip()
                    else:
                        description = desc_content
                    
                    break
                elif next_line.startswith('* -'):
                    # Next entry started, no description found
                    break
                elif next_line == '':
                    # Empty line, continue looking
                    j += 1
                    continue
                else:
                    j += 1
                    continue
                
            entries.append({
                'citation_key': citation_key,
                'description': description,
                'url': url
            })
        
        i += 1
    
    return entries


def extract_citation_keys_from_content(content: str) -> List[Tuple[str, str]]:
    """
    Extract all citation key definitions from bibliography content.
    
    Looks for :bibentry: role patterns:
    - :bibentry:`gui_XxxYyyZzz:CITATION-KEY`
    
    Args:
        content: The bibliography content text
        
    Returns:
        List of (guideline_id, citation_key) tuples found
    """
    entries = []
    
    # Pattern for :bibentry: role
    for match in BIBENTRY_ROLE_PATTERN.finditer(content):
        guideline_id = match.group(1)
        citation_key = match.group(2)
        entries.append((guideline_id, citation_key))
    
    # Also support legacy plain text format for backwards compatibility
    # Pattern for bold citation key: **[KEY]**
    bold_citation = re.compile(r'\*\*\[([A-Z][A-Z0-9-]*[A-Z0-9])\]\*\*')
    for match in bold_citation.finditer(content):
        # For legacy format, we don't have guideline_id
        entries.append((None, match.group(1)))
    
    return entries


def extract_citation_references(content: str) -> List[Tuple[str, str]]:
    """
    Extract all citation references from guideline content.
    
    Looks for :cite: role patterns:
    - :cite:`gui_XxxYyyZzz:CITATION-KEY`
    
    Args:
        content: The guideline or rationale content
        
    Returns:
        List of (guideline_id, citation_key) tuples found
    """
    refs = []
    
    # Pattern for :cite: role
    for match in CITE_ROLE_PATTERN.finditer(content):
        guideline_id = match.group(1)
        citation_key = match.group(2)
        refs.append((guideline_id, citation_key))
    
    # Also support legacy plain text format for backwards compatibility
    # But exclude matches that are part of :cite: or :bibentry: roles
    plain_refs = PLAIN_CITATION_REF_PATTERN.findall(content)
    # Filter out keys that are already captured via roles
    role_keys = {key for _, key in refs}
    for key in plain_refs:
        if key not in role_keys:
            refs.append((None, key))
    
    return refs


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
    3. Validates guideline ID matches in :cite: and :bibentry: roles
    4. Checks for URL consistency across guidelines
    5. Optionally validates URL accessibility
    6. Checks that citation references match definitions
    
    Args:
        app: The Sphinx application
        env: The Sphinx environment
    """
    logger.info("Validating bibliography entries...")
    
    data = SphinxNeedsData(env)
    all_needs = data.get_needs_view()
    
    # Collect data for validation
    all_urls: List[Tuple[str, str, str]] = []  # (url, guideline_id, source_file)
    url_to_guidelines: Dict[str, List[str]] = defaultdict(list)
    citation_definitions: Dict[str, List[str]] = defaultdict(list)  # key -> [guideline_ids]
    citation_references: Dict[str, Set[str]] = defaultdict(set)  # guideline_id -> {referenced_keys}
    
    # Track full bibliography entry data per URL for consistency checking
    # url -> [(guideline_id, citation_key, description)]
    url_entry_data: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    
    errors = []
    warnings = []
    
    # First pass: collect guidelines and their bibliographies
    guidelines = {k: v for k, v in all_needs.items() if v.get("type") == "guideline"}
    
    if not guidelines:
        logger.info("No guidelines found, skipping bibliography validation")
        return
    
    pbar = get_tqdm(
        iterable=guidelines.items(),
        desc="Validating bibliography citations",
        bar_format=bar_format,
        unit="guideline",
    )
    
    for guideline_id, guideline in pbar:
        pbar.set_postfix(guideline=guideline_id[:20])
        source_file = guideline.get("docname", "unknown")
        
        # Get the full guideline content for :cite: role validation
        guideline_content = guideline.get("content", "")
        
        # Check :cite: roles in guideline content for guideline ID mismatch and key format
        for match in CITE_ROLE_PATTERN.finditer(guideline_content):
            role_gid = match.group(1)
            citation_key = match.group(2)
            
            # Check for guideline ID mismatch
            if role_gid != guideline_id:
                errors.append(
                    f"Guideline ID mismatch in :cite: role ({source_file}):\n"
                    f"  Role uses: {role_gid}\n"
                    f"  Current guideline: {guideline_id}\n"
                    f"  Copy-paste fix: :cite:`{guideline_id}:{citation_key}`"
                )
            
            # Check citation key format
            if not VALID_CITATION_KEY_PATTERN.match(citation_key):
                suggested_key = suggest_citation_key(citation_key)
                errors.append(
                    f"Invalid citation key in :cite: role ({source_file}):\n"
                    f"  Key: {citation_key}\n"
                    f"  Must be UPPERCASE-WITH-HYPHENS (e.g., RUST-REF-UNION)\n"
                    f"  Copy-paste fix: :cite:`{guideline_id}:{suggested_key}`"
                )
        
        # Check for bibliography children
        parent_needs_back = guideline.get("parent_needs_back", [])
        
        for child_id in parent_needs_back:
            if child_id in all_needs:
                child = all_needs[child_id]
                
                if child.get("type") == "bibliography":
                    bib_content = child.get("content", "")
                    
                    # Check :bibentry: roles for guideline ID mismatch and key format
                    for match in BIBENTRY_ROLE_PATTERN.finditer(bib_content):
                        role_gid = match.group(1)
                        citation_key = match.group(2)
                        
                        # Check for guideline ID mismatch
                        if role_gid != guideline_id:
                            errors.append(
                                f"Guideline ID mismatch in :bibentry: role ({source_file}):\n"
                                f"  Role uses: {role_gid}\n"
                                f"  Current guideline: {guideline_id}\n"
                                f"  Copy-paste fix: :bibentry:`{guideline_id}:{citation_key}`"
                            )
                        
                        # Check citation key format
                        if not VALID_CITATION_KEY_PATTERN.match(citation_key):
                            suggested_key = suggest_citation_key(citation_key)
                            errors.append(
                                f"Invalid citation key in :bibentry: role ({source_file}):\n"
                                f"  Key: {citation_key}\n"
                                f"  Must be UPPERCASE-WITH-HYPHENS (e.g., RUST-REF-UNION)\n"
                                f"  Copy-paste fix: :bibentry:`{guideline_id}:{suggested_key}`"
                            )
                        else:
                            # Only track valid keys
                            citation_definitions[citation_key].append(guideline_id)
                    
                    # Extract full bibliography entries for consistency checking
                    entries = extract_bibliography_entries(bib_content)
                    for entry in entries:
                        url = entry.get('url', '')
                        if url:
                            all_urls.append((url, guideline_id, source_file))
                            url_to_guidelines[url].append(guideline_id)
                            url_entry_data[url].append((
                                guideline_id,
                                entry.get('citation_key', ''),
                                entry.get('description', '')
                            ))
        
        # Collect citation references from guideline content
        refs = extract_citation_references(guideline_content)
        for ref_tuple in refs:
            ref_gid, ref_key = ref_tuple
            citation_references[guideline_id].add(ref_key)
    
    pbar.close()
    
    # Check for URL consistency (same URL must use same citation key and description)
    logger.info("Checking URL consistency across guidelines...")
    for url, entry_list in url_entry_data.items():
        if len(entry_list) > 1:
            # Multiple guidelines use this URL - check for consistency
            first_guideline, first_key, first_desc = entry_list[0]
            
            inconsistent_guidelines = []
            for guideline_id, citation_key, description in entry_list[1:]:
                if citation_key != first_key or description != first_desc:
                    inconsistent_guidelines.append(guideline_id)
            
            if inconsistent_guidelines:
                # Build copy-pasteable fixes for each inconsistent guideline
                fixes = []
                for gid in inconsistent_guidelines:
                    fix = (
                        f"  In {gid}, replace the bibliography entry with:\n"
                        f"    * - :bibentry:`{gid}:{first_key}`\n"
                        f"      - {first_desc}{url}"
                    )
                    fixes.append(fix)
                
                msg = (
                    f"Inconsistent bibliography entry for URL:\n"
                    f"  URL: {url}\n"
                    f"  Canonical entry (from {first_guideline}):\n"
                    f"    Citation key: [{first_key}]\n"
                    f"    Description: {first_desc}\n"
                    f"  Guidelines with inconsistent entries: {', '.join(inconsistent_guidelines)}\n"
                    f"\n"
                    f"  Copy-paste fixes:\n" +
                    "\n\n".join(fixes)
                )
                if app.config.bibliography_fail_on_inconsistent:
                    errors.append(msg)
                else:
                    warnings.append(msg)
    
    # Validate URLs if enabled
    if app.config.bibliography_check_urls and all_urls:
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
    elif not app.config.bibliography_check_urls:
        logger.info("URL accessibility validation disabled (set bibliography_check_urls = True to enable)")
    
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
                            # Check for the citation key in the bibliography content
                            if ref in bib_content:
                                found_in_own_bib = True
                                break
                    
                    if not found_in_own_bib:
                        source_file = guideline.get("docname", "unknown")
                        warnings.append(
                            f"Undefined citation reference in {source_file}:\n"
                            f"  Reference: [{ref}]\n"
                            f"  Guideline: {guideline_id}\n"
                            f"  Action: Add this citation to the bibliography or remove the reference"
                        )
    
    # Check for unused citations
    if app.config.bibliography_check_unused:
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
    
    # Report errors and fail build
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
    app.add_config_value('bibliography_fail_on_inconsistent', True, 'env')
    app.add_config_value('bibliography_check_unused', False, 'env')
    
    # Connect to the consistency check phase
    app.connect("env-check-consistency", validate_bibliography)
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
    }
