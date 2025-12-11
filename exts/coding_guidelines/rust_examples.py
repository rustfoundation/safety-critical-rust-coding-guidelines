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

Hidden lines (prefixed with `# `) can be shown or hidden based on configuration.
"""

import re
from typing import List, Optional, Tuple

from docutils import nodes
from docutils.parsers.rst import Directive, directives
from sphinx.application import Sphinx
from sphinx.util import logging

logger = logging.getLogger(__name__)


# Valid rustdoc attributes
RUSTDOC_ATTRIBUTES = {
    "ignore": "This example is not compiled or tested",
    "compile_fail": "This example should fail to compile",
    "should_panic": "This example should panic at runtime",
    "no_run": "This example is compiled but not executed",
}


def parse_compile_fail_error(value: str) -> Tuple[bool, Optional[str]]:
    """
    Parse compile_fail option value.
    
    Returns:
        Tuple of (is_compile_fail, optional_error_code)
    
    Examples:
        "" -> (True, None)
        "E0277" -> (True, "E0277")
    """
    if not value or value.lower() in ("true", "yes", "1"):
        return (True, None)
    # Check if it looks like an error code (E followed by digits)
    if re.match(r"^E\d{4}$", value.strip()):
        return (True, value.strip())
    return (True, None)


def process_hidden_lines(code: str, show_hidden: bool = False) -> Tuple[str, str]:
    """
    Process code to handle hidden lines (prefixed with `# `).
    
    Args:
        code: The raw code with potential hidden line markers
        show_hidden: Whether to include hidden lines in rendered output
        
    Returns:
        Tuple of (display_code, full_code_for_testing)
    """
    lines = code.split('\n')
    display_lines = []
    full_lines = []
    
    for line in lines:
        # Check for hidden line marker (rustdoc style: line starts with # followed by space or nothing)
        if line.startswith('# ') or line == '#':
            # Hidden line - always include in full code
            full_lines.append(line[2:] if line.startswith('# ') else '')
            if show_hidden:
                # Show with a visual indicator
                display_lines.append(line)
        else:
            display_lines.append(line)
            full_lines.append(line)
    
    return '\n'.join(display_lines), '\n'.join(full_lines)


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
            :show_hidden:
            
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
        "compile_fail": directives.unchanged,  # Can be flag or error code
        "should_panic": directives.unchanged,  # Can be flag or expected message
        "no_run": directives.flag,
        # Display options
        "show_hidden": directives.flag,  # Show hidden lines in rendered output
        # Metadata
        "name": directives.unchanged,  # Optional name for the example
    }
    
    def run(self) -> List[nodes.Node]:
        env = self.state.document.settings.env
        
        # Get configuration for showing hidden lines globally
        show_hidden_global = getattr(env.config, 'rust_examples_show_hidden', False)
        show_hidden = 'show_hidden' in self.options or show_hidden_global
        
        # Parse the code content
        raw_code = '\n'.join(self.content)
        display_code, full_code = process_hidden_lines(raw_code, show_hidden)
        
        # Determine which rustdoc attribute is set (only one should be set)
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
        
        # Store metadata for extraction by the test runner
        example_name = self.options.get('name', '')
        
        # Create the container node
        container = nodes.container()
        container['classes'].append('rust-example-container')
        
        # Add the badge if there's an attribute
        if rustdoc_attr:
            badge = nodes.container()
            badge['classes'].append('rust-example-badge')
            badge['classes'].append(f'rust-example-badge-{rustdoc_attr.replace("_", "-")}')
            
            badge_text = rustdoc_attr
            if attr_value:
                badge_text += f"({attr_value})"
            
            badge_para = nodes.paragraph()
            badge_para += nodes.Text(badge_text)
            badge += badge_para
            container += badge
        
        # Create the code block
        code_node = nodes.literal_block(display_code, display_code)
        code_node['language'] = 'rust'
        code_node['classes'].append('rust-example-code')
        
        # Store rustdoc metadata as custom attributes for later extraction
        code_node['rustdoc_attr'] = rustdoc_attr
        code_node['rustdoc_attr_value'] = attr_value
        code_node['rustdoc_full_code'] = full_code
        code_node['rustdoc_example_name'] = example_name
        
        # Store source location for error reporting
        source, line = self.state_machine.get_source_and_line(self.lineno)
        code_node['source'] = source
        code_node['line'] = line
        
        container += code_node
        
        return [container]


class RustExampleCollector:
    """
    Collector that gathers all rust-example code blocks for testing.
    """
    
    def __init__(self):
        self.examples = []
    
    def collect(self, app, doctree, docname):
        """Collect rust examples from the doctree."""
        for node in doctree.traverse(nodes.literal_block):
            if node.get('language') == 'rust' and 'rustdoc_full_code' in node.attributes:
                example = {
                    'docname': docname,
                    'source': node.get('source', ''),
                    'line': node.get('line', 0),
                    'code': node.get('rustdoc_full_code', ''),
                    'display_code': node.astext(),
                    'attr': node.get('rustdoc_attr'),
                    'attr_value': node.get('rustdoc_attr_value'),
                    'name': node.get('rustdoc_example_name', ''),
                }
                self.examples.append(example)


def add_css(app: Sphinx):
    """Add CSS for rust-example styling."""
    css = """
/* Rust Example Container */
.rust-example-container {
    margin: 1em 0;
    border-radius: 4px;
    overflow: hidden;
}

/* Badge styling */
.rust-example-badge {
    padding: 0.3em 0.8em;
    font-family: monospace;
    font-size: 0.85em;
    font-weight: bold;
    border-bottom: 1px solid rgba(0, 0, 0, 0.1);
}

.rust-example-badge p {
    margin: 0;
}

.rust-example-badge-ignore {
    background-color: #6c757d;
    color: white;
}

.rust-example-badge-ignore::before {
    content: "⏭ ";
}

.rust-example-badge-compile-fail {
    background-color: #dc3545;
    color: white;
}

.rust-example-badge-compile-fail::before {
    content: "✗ ";
}

.rust-example-badge-should-panic {
    background-color: #fd7e14;
    color: white;
}

.rust-example-badge-should-panic::before {
    content: "💥 ";
}

.rust-example-badge-no-run {
    background-color: #17a2b8;
    color: white;
}

.rust-example-badge-no-run::before {
    content: "⚙ ";
}

/* Hidden lines styling (when shown) */
.rust-example-code .hidden-line {
    opacity: 0.6;
    font-style: italic;
}

/* Code block within container */
.rust-example-container .rust-example-code {
    margin-top: 0;
    border-top-left-radius: 0;
    border-top-right-radius: 0;
}
"""
    
    import os
    css_path = os.path.join(app.outdir, "_static", "rust_examples.css")
    os.makedirs(os.path.dirname(css_path), exist_ok=True)
    with open(css_path, "w") as f:
        f.write(css)


def inject_css_link(app, pagename, templatename, context, doctree):
    """Inject CSS link into HTML pages that have rust examples."""
    if doctree is None:
        return
    
    # Check if this page has any rust examples
    has_examples = False
    for node in doctree.traverse(nodes.container):
        if 'rust-example-container' in node.get('classes', []):
            has_examples = True
            break
    
    if has_examples:
        # Add CSS to metatags or similar
        if 'metatags' not in context:
            context['metatags'] = ''
        context['metatags'] += '\n<link rel="stylesheet" href="_static/rust_examples.css" type="text/css" />'


def build_finished(app, exception):
    """Write CSS file when build finishes."""
    if exception is not None:
        return
    add_css(app)


def setup(app: Sphinx):
    """Setup the rust-example extension."""
    
    # Register the directive
    app.add_directive('rust-example', RustExampleDirective)
    
    # Configuration options
    app.add_config_value('rust_examples_show_hidden', False, 'env')
    app.add_config_value('rust_examples_prelude_file', None, 'env')
    
    # Connect to build events
    app.connect('build-finished', build_finished)
    
    return {
        'version': '0.1',
        'parallel_read_safe': True,
    }
