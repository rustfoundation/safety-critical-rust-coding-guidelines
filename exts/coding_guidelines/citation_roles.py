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

from docutils import nodes
from sphinx.util.docutils import SphinxRole

# Pattern for validating citation keys: UPPERCASE-WITH-HYPHENS-AND-NUMBERS
CITATION_KEY_PATTERN = re.compile(r'^[A-Z][A-Z0-9-]*[A-Z0-9]$')

# Pattern for parsing role content: guideline_id:CITATION-KEY
ROLE_CONTENT_PATTERN = re.compile(r'^(gui_[a-zA-Z0-9]+):([A-Z][A-Z0-9-]*[A-Z0-9])$')


def parse_role_content(text):
    """
    Parse the role content to extract guideline ID and citation key.
    
    Args:
        text: Role content in format "gui_XxxYyyZzz:CITATION-KEY"
        
    Returns:
        Tuple of (guideline_id, citation_key) or (None, None) if invalid
    """
    match = ROLE_CONTENT_PATTERN.match(text)
    if match:
        return match.group(1), match.group(2)
    return None, None


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


class CiteRole(SphinxRole):
    """
    Role for creating citation references in guideline text.
    
    Usage: :cite:`gui_XxxYyyZzz:CITATION-KEY`
    
    Renders as: [CITATION-KEY] (as a hyperlink to the bibliography entry)
    """
    
    def run(self):
        guideline_id, citation_key = parse_role_content(self.text)
        
        if guideline_id is None:
            # Invalid format - show error
            msg = self.inliner.reporter.error(
                f'Invalid :cite: format: "{self.text}". '
                f'Expected format: :cite:`gui_XxxYyyZzz:CITATION-KEY`',
                line=self.lineno
            )
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
    """
    
    def run(self):
        guideline_id, citation_key = parse_role_content(self.text)
        
        if guideline_id is None:
            # Invalid format - show error
            msg = self.inliner.reporter.error(
                f'Invalid :bibentry: format: "{self.text}". '
                f'Expected format: :bibentry:`gui_XxxYyyZzz:CITATION-KEY`',
                line=self.lineno
            )
            prb = self.inliner.problematic(self.rawtext, self.rawtext, msg)
            return [prb], [msg]
        
        # Create the anchor ID
        anchor_id = make_anchor_id(guideline_id, citation_key)
        
        # Create a target node (the anchor)
        target = nodes.target('', '', ids=[anchor_id])
        
        # Create the visible text as bold [CITATION-KEY]
        strong = nodes.strong('', f'[{citation_key}]')
        strong['classes'].append('bibentry-key')
        
        # Create the back link using raw HTML for the onclick handler
        back_link = nodes.raw(
            '',
            '<a href="javascript:void(0)" onclick="history.back()" '
            'class="bibentry-back" title="Return to citation">↩</a>',
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
    
    # Add CSS for styling
    app.add_css_file('citation.css')
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
        'parallel_write_safe': True,
    }
