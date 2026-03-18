# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

"""
Custom Sphinx roles for bibliography citations in coding guidelines.

This module provides two roles for linking in-text citations to bibliography entries:

1. :cite:`guideline_id:CITATION-KEY` - Creates a clickable reference in the guideline text
2. :bibentry:`guideline_id:CITATION-KEY` - Creates an anchor in the bibliography table

The guideline_id prefix ensures citations are namespaced per-guideline, avoiding
conflicts when multiple guidelines use the same citation key (e.g., RUST-REF-UNION).

Example usage in RST:
    
    .. guideline:: Union Field Validity
       :id: gui_Abc123XyzQrs
       
       As documented in :cite:`gui_Abc123XyzQrs:RUST-REF-UNION`, unions have
       specific safety requirements.
       
       .. bibliography::
          :id: bib_Abc123XyzQrs
          
          .. list-table::
             :header-rows: 0
             
             * - :bibentry:`gui_Abc123XyzQrs:RUST-REF-UNION`
               - The Rust Reference. "Unions." https://doc.rust-lang.org/...

When using generate_guideline_templates.py, the guideline ID prefix is automatically
included in the generated RST.
"""

import re
from typing import Optional

from docutils import nodes
from sphinx.util.docutils import SphinxRole

# Pattern for validating citation keys: UPPERCASE-WITH-HYPHENS-AND-NUMBERS
VALID_CITATION_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9-]*[A-Z0-9]$')

# Pattern for parsing role content: guideline_id:CITATION-KEY
# Permissive pattern to capture any key format for validation
ROLE_CONTENT_PATTERN = re.compile(r'^(gui_[a-zA-Z0-9]+):(.+)$')


def parse_role_content(text):
    """
    Parse the role content to extract guideline ID and citation key.
    
    Args:
        text: Role content in format "gui_XxxYyyZzz:CITATION-KEY"
        
    Returns:
        Tuple of (guideline_id, citation_key) or (None, None) if format is invalid
        Note: Returns the key even if it's invalid format (for better error messages)
    """
    match = ROLE_CONTENT_PATTERN.match(text)
    if match:
        return match.group(1), match.group(2)
    return None, None


def validate_citation_key(key: str) -> tuple:
    """
    Validate that a citation key follows the required format.
    
    Args:
        key: The citation key to validate
        
    Returns:
        Tuple of (is_valid, suggested_fix)
    """
    if not key:
        return False, "CITATION-KEY"
    
    if VALID_CITATION_KEY_PATTERN.match(key):
        return True, key
    
    # Generate suggested fix
    suggested = key.upper()
    suggested = re.sub(r'[\s_]+', '-', suggested)
    suggested = re.sub(r'[^A-Z0-9-]', '', suggested)
    suggested = suggested.strip('-')
    suggested = re.sub(r'-+', '-', suggested)
    
    if not suggested or len(suggested) < 2:
        suggested = "CITATION-KEY"
    elif not suggested[0].isalpha():
        suggested = "REF-" + suggested
    
    return False, suggested


def make_anchor_id(guideline_id, citation_key):
    """
    Generate a unique anchor ID for a bibliography entry.
    
    Args:
        guideline_id: The guideline ID (e.g., "gui_Abc123XyzQrs")
        citation_key: The citation key (e.g., "RUST-REF-UNION")
        
    Returns:
        Anchor ID string (e.g., "cite-gui_Abc123XyzQrs-RUST-REF-UNION")
    """
    return f"cite-{guideline_id}-{citation_key}"


def find_guideline_id_from_context(inliner, lineno: int) -> Optional[str]:
    """
    Find the guideline ID that contains the current line.
    
    Searches the document source for :id: gui_xxx patterns that appear
    before the current line number.
    
    Args:
        inliner: The docutils inliner object
        lineno: Current line number
        
    Returns:
        The guideline ID if found, None otherwise
    """
    try:
        # Get the source from the document
        source = inliner.document.settings._source
        if not source:
            return None
        
        lines = source.split('\n')
        
        # Pattern to match guideline ID: :id: gui_xxx
        id_pattern = re.compile(r':id:\s*(gui_[a-zA-Z0-9]+)')
        
        # Search backwards from current line to find the most recent guideline ID
        found_id = None
        for i in range(min(lineno - 1, len(lines) - 1), -1, -1):
            match = id_pattern.search(lines[i])
            if match:
                found_id = match.group(1)
                break
        
        return found_id
    except Exception:
        return None


def suggest_role_fix(text: str, role_type: str, guideline_id: Optional[str] = None) -> str:
    """
    Suggest a corrected role format based on invalid input.
    
    Args:
        text: The invalid role content
        role_type: Either 'cite' or 'bibentry'
        guideline_id: The detected guideline ID, if available
        
    Returns:
        A suggested fix string
    """
    # Use detected guideline ID or placeholder
    gid = guideline_id if guideline_id else "gui_YOUR_GUIDELINE_ID"
    
    # Try to extract what looks like a citation key
    
    # Check if it's just a citation key (missing guideline ID prefix)
    if re.match(r'^[A-Z][A-Z0-9-]*[A-Z0-9]$', text):
        return f":{role_type}:`{gid}:{text}`"
    
    # Check if guideline ID is malformed (e.g., missing gui_ prefix)
    colon_match = re.match(r'^([^:]+):([A-Z][A-Z0-9-]*[A-Z0-9])$', text)
    if colon_match:
        potential_id, key = colon_match.groups()
        if not potential_id.startswith('gui_'):
            # Use detected ID if available, otherwise try to fix the provided one
            if guideline_id:
                return f":{role_type}:`{guideline_id}:{key}`"
            else:
                return f":{role_type}:`gui_{potential_id}:{key}`"
    
    # Check for common mistakes like using brackets
    bracket_match = re.search(r'\[([A-Z][A-Z0-9-]*[A-Z0-9])\]', text)
    if bracket_match:
        key = bracket_match.group(1)
        return f":{role_type}:`{gid}:{key}`"
    
    # Generic suggestion
    return f":{role_type}:`{gid}:YOUR-CITATION-KEY`"


class CiteRole(SphinxRole):
    """
    Role for creating citation references in guideline text.
    
    Usage: :cite:`gui_XxxYyyZzz:CITATION-KEY`
    
    Renders as: [CITATION-KEY] (as a hyperlink to the bibliography entry)
    """
    
    def run(self):
        guideline_id, citation_key = parse_role_content(self.text)
        
        # Try to detect the guideline ID from context
        detected_id = find_guideline_id_from_context(self.inliner, self.lineno)
        
        if guideline_id is None:
            # Invalid format - show error with copy-pasteable suggestion
            suggested_fix = suggest_role_fix(self.text, 'cite', detected_id)
            error_msg = (
                f'Invalid :cite: format: "{self.text}".\n'
                f'  Expected format: :cite:`gui_XxxYyyZzz:CITATION-KEY`\n'
                f'  Suggested fix: {suggested_fix}'
            )
            msg = self.inliner.reporter.error(error_msg, line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Validate guideline ID matches the current guideline
        if detected_id and guideline_id != detected_id:
            error_msg = (
                f'Guideline ID mismatch in :cite: role.\n'
                f'  Role uses: {guideline_id}\n'
                f'  Current guideline: {detected_id}\n'
                f'  Copy-paste fix: :cite:`{detected_id}:{citation_key}`'
            )
            msg = self.inliner.reporter.error(error_msg, line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Validate citation key format
        is_valid_key, suggested_key = validate_citation_key(citation_key)
        if not is_valid_key:
            effective_id = detected_id if detected_id else guideline_id
            error_msg = (
                f'Invalid citation key "{citation_key}" in :cite: role.\n'
                f'  Must be UPPERCASE-WITH-HYPHENS (e.g., RUST-REF-UNION)\n'
                f'  Copy-paste fix: :cite:`{effective_id}:{suggested_key}`'
            )
            msg = self.inliner.reporter.error(error_msg, line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Create the anchor ID
        anchor_id = make_anchor_id(guideline_id, citation_key)
        
        # Create a reference node that links to the bibliography entry
        ref_node = nodes.reference('', '', internal=True)
        ref_node['refid'] = anchor_id
        ref_node['classes'].append('citation-ref')
        
        # The visible text is [CITATION-KEY]
        ref_node += nodes.Text(f'[{citation_key}]')
        
        return [ref_node], []


class BibEntryRole(SphinxRole):
    """
    Role for creating bibliography entry anchors.
    
    Usage: :bibentry:`gui_XxxYyyZzz:CITATION-KEY`
    
    Renders as: [CITATION-KEY] ↩ (bold, with an anchor for linking and a back button)
    
    The back button has smart behavior:
    - If clicked after navigating from a :cite: link, returns to that location
    - If accessed directly (URL, scrolling), jumps to the first :cite: reference
    """
    
    def run(self):
        guideline_id, citation_key = parse_role_content(self.text)
        
        # Try to detect the guideline ID from context
        detected_id = find_guideline_id_from_context(self.inliner, self.lineno)
        
        if guideline_id is None:
            # Invalid format - show error with copy-pasteable suggestion
            suggested_fix = suggest_role_fix(self.text, 'bibentry', detected_id)
            error_msg = (
                f'Invalid :bibentry: format: "{self.text}".\n'
                f'  Expected format: :bibentry:`gui_XxxYyyZzz:CITATION-KEY`\n'
                f'  Suggested fix: {suggested_fix}'
            )
            msg = self.inliner.reporter.error(error_msg, line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Validate guideline ID matches the current guideline
        if detected_id and guideline_id != detected_id:
            error_msg = (
                f'Guideline ID mismatch in :bibentry: role.\n'
                f'  Role uses: {guideline_id}\n'
                f'  Current guideline: {detected_id}\n'
                f'  Copy-paste fix: :bibentry:`{detected_id}:{citation_key}`'
            )
            msg = self.inliner.reporter.error(error_msg, line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Validate citation key format
        is_valid_key, suggested_key = validate_citation_key(citation_key)
        if not is_valid_key:
            effective_id = detected_id if detected_id else guideline_id
            error_msg = (
                f'Invalid citation key "{citation_key}" in :bibentry: role.\n'
                f'  Must be UPPERCASE-WITH-HYPHENS (e.g., RUST-REF-UNION)\n'
                f'  Copy-paste fix: :bibentry:`{effective_id}:{suggested_key}`'
            )
            msg = self.inliner.reporter.error(error_msg, line=self.lineno)
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Create the anchor ID
        anchor_id = make_anchor_id(guideline_id, citation_key)
        
        # Create a target node (the anchor)
        target = nodes.target('', '', ids=[anchor_id])
        
        # Create the visible text as bold [CITATION-KEY]
        strong = nodes.strong('', f'[{citation_key}]')
        strong['classes'].append('bibentry-key')
        
        # Create the back link using raw HTML
        # Calls citationGoBack() which handles smart navigation
        back_link = nodes.raw(
            '',
            f'<a href="javascript:void(0)" onclick="citationGoBack(\'{anchor_id}\')" '
            f'class="bibentry-back" title="Return to citation">↩</a>',
            format='html'
        )
        
        # Return the target (anchor), visible text, and back link
        return [target, strong, back_link], []


def setup(app):
    """
    Register the citation roles with Sphinx.
    """
    app.add_role('cite', CiteRole())
    app.add_role('bibentry', BibEntryRole())
    
    # Add CSS and JS for styling and navigation
    app.add_css_file('citation.css')
    app.add_js_file('citation.js')
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
