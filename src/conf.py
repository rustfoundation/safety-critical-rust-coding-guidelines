# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

# -- Path setup --------------------------------------------------------------

import os
import sys

sys.path.append(os.path.abspath("../exts"))

# -- Project information -----------------------------------------------------

project = 'Safety-Critical Rust Coding Guidelines'
copyright = '2025, Contributors to Coding Guidelines Subcommittee'
author = 'Contributors to Coding Guidelines Subcommittee'
release = '0.1'

# -- General configuration ---------------------------------------------------

# Add sphinx-needs to extensions
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.viewcode',
    'sphinx.ext.autosectionlabel',
    'sphinx_needs',
    'coding_guidelines',
]

# Basic needs configuration
needs_id_regex = "^[A-Za-z0-9_]+"
needs_title_optional = True
needs_id_from_title = False
needs_build_json = True

# Configure sphinx-needs
needs_types = [
    {
        "directive": "guideline",
        "title": "Guideline",
        "prefix": "gui_",
        "color": "#BFD8D2",
        "style": "node"
    },
    {
        "directive": "rationale",
        "title": "Rationale",
        "prefix": "rat_",
        "color": "#DF744A",
        "style": "node"
    },
    {
        "directive": "compliant_example",
        "title": "Compliant Example",
        "prefix": "compl_ex_",
        "color": "#729FCF",
        "style": "node"
    },
    {
        "directive": "non_compliant_example",
        "title": "Non-Compliant Example",
        "prefix": "non_compl_ex_",
        "color": "#729FCF",
        "style": "node"
    }
]

# Define custom sections for needs
needs_layouts = {
    "guideline": {
        "content": [
            "content",
            "rationale",
            "non_compliant_example",
            "compliant_example"
        ]
    }
}

# Tell sphinx-needs which sections to render
needs_render_contexts = {
    "guideline": {
        "content": ["content"],
        "extra_content": ["rationale", "non_compliant_example", "non_compliant_example"]
    }
}

# Make sure these sections are included in the JSON
needs_extra_sections = ["rationale", "compliant_example", "non_compliant_example"]

needs_statuses = [
    dict(name="draft", description="This guideline is in draft stage", color="#999999"),
    dict(name="approved", description="This guideline has been approved", color="#00FF00"),
    dict(name="retired", description="This guideline is retired", color="#FF0000"),
]

needs_tags = [
    dict(name="security", description="Security-related guideline"),
    dict(name="performance", description="Performance-related guideline"),
    dict(name="readability", description="Readability-related guideline"),
    dict(name="reduce-human-error", description="Reducing human error guideline"),
    dict(name="numerics", description="Numerics-related guideline"),
    dict(name="undefined-behavior", description="Numerics-related guideline"),
    dict(name="stack-overflow", description="Stack-overflow-related guideline"),

    dict(name="subset", description="Guideline associated with the language-subset profile"),
    dict(name="defect", description="Guideline associated with the defect-prevention profile"),
]

needs_categories = [
    dict(name="mandatory", description="This guideline is mandatory", color="#999999"),
    dict(name="required", description="This guideline is required", color="#FFCC00"),
    dict(name="advisory", description="This guideline is advisory, should be followed when able", color="#FFCC00"),
    dict(name="disapplied", description="This guideline is advisory, should be followed when able", color="#FFCC00"),
]

needs_decidabilities = [
    dict(name="decidable", description="This guideline can be automatically checked with tooling", color="#999999"),
    dict(name="undecidable", description="This guideline cannot be automatically checked with tooling", color="#999999"),
]

needs_scopes = [
    dict(name="module", description="This guideline can be checked at the module level", color="#999999"),
    dict(name="crate", description="This guideline can be checked at the crate level", color="#FFCC00"),
    dict(name="system", description="This guideline must be checked alongside the entire source", color="#FFCC00"),
]

needs_releases = [
    dict(name="1.85.0", description="This guideline can be checked at the module level", color="#999999"),
    dict(name="1.85.1", description="This guideline can be checked at the module level", color="#999999"),
]

# Enable needs export
needs_extra_options = ["category", "recommendation", "fls", "decidability", "scope", "release"]


# Required guideline fields
required_guideline_fields = ['category', 'release', 'fls', 'decidability', 'scope', 'tags'] # Id is automatically generated

# -- Options for HTML output -------------------------------------------------

# Configure the theme
html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
