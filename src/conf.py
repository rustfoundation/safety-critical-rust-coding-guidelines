# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

# -- Path setup --------------------------------------------------------------

import os
import sys

sys.path.append(os.path.abspath("../exts"))

# -- Project information -----------------------------------------------------

project = "Safety-Critical Rust Coding Guidelines"
copyright = "2025, Contributors to Coding Guidelines Subcommittee"
author = "Contributors to Coding Guidelines Subcommittee"
release = "0.1"

# -- General configuration ---------------------------------------------------

# Add sphinx-needs to extensions
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosectionlabel",
    "sphinx_needs",
    "coding_guidelines",
]

# Show hidden lines in all examples (default: False)
rust_examples_show_hidden = False

# Path to shared prelude (default: None)
rust_examples_prelude_file = "src/examples_prelude.rs"

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
        "style": "node",
    },
    {
        "directive": "rationale",
        "title": "Rationale",
        "prefix": "rat_",
        "color": "#DF744A",
        "style": "node",
    },
    {
        "directive": "compliant_example",
        "title": "Compliant Example",
        "prefix": "compl_ex_",
        "color": "#729FCF",
        "style": "node",
    },
    {
        "directive": "non_compliant_example",
        "title": "Non-Compliant Example",
        "prefix": "non_compl_ex_",
        "color": "#729FCF",
        "style": "node",
    },
    {
        "directive": "bibliography",
        "title": "Bibliography",
        "prefix": "bib_",
        "color": "#A8D8EA",
        "style": "node",
    },
]

# Define custom sections for needs
needs_layouts = {
    "guideline": {
        "content": [
            "content",
            "rationale",
            "non_compliant_example",
            "compliant_example",
            "bibliography",
        ]
    }
}

# Tell sphinx-needs which sections to render
needs_render_contexts = {
    "guideline": {
        "content": ["content"],
        "extra_content": [
            "rationale",
            "non_compliant_example",
            "non_compliant_example",
            "bibliography",
        ],
    }
}

# Make sure these sections are included in the JSON
needs_extra_sections = ["rationale", "compliant_example", "non_compliant_example", "bibliography"]

needs_statuses = [
    dict(name="draft", description="This guideline is in draft stage", color="#999999"),
    dict(
        name="approved", description="This guideline has been approved", color="#00FF00"
    ),
    dict(name="retired", description="This guideline is retired", color="#FF0000"),
]

needs_tags = [
    dict(name="security", description="Security-related guideline"),
    dict(name="safety", description="The degree to which a product or system avoids endangering human life, health, property, or the environment under defined operating conditions."),
    dict(name="performance", description="Performance-related guideline"),
    dict(name="readability", description="Readability-related guideline"),
    dict(name="understandability", description="Understandability is a sub-characteristic of usability in the ISO/IEC 25000 quality model, which measures how easy it is for users to understand the functions and usage of a software product. It is also a separate quality characteristic for data, referring to how well data can be read and interpreted by users with the help of appropriate languages, symbols, and units."),
    dict(name="reduce-human-error", description="Guideline that helps prevent human error"),
    dict(name="numerics", description="Numerics-related guideline"),
    dict(name="undefined-behavior", description="Guideline related to Undefined Behavior"),
    dict(name="stack-overflow", description="Guideline related to Stack Overflow"),

    dict(name="maintainability", description="How effectively and efficiently a product or system can be modified. This includes improvements, fault corrections, and adaptations to changes in the environment or requirements. It is considered a crucial software quality characteristic."),
    dict(name="portability", description="The degree to which a system, product, or component can be effectively and efficiently transferred from one hardware, software, or other operational or usage environment to another."),
    dict(name="surprising-behavior", description="Guideline related to surprising or unexpected behavior"),

    dict(name="types", description="Guideline associated with the correct use of types"),
    dict(name="subset", description="Guideline associated with the language-subset profile"),
    dict(name="defect", description="Guideline associated with the defect-prevention profile"),

    dict(name="unsafe", description="Guidelines that interact with or involve the unsafe keyword"),
]

needs_categories = [
    dict(name="mandatory", description="This guideline is mandatory", color="#999999"),
    dict(name="required", description="This guideline is required", color="#FFCC00"),
    dict(
        name="advisory",
        description="This guideline is advisory, should be followed when able",
        color="#FFCC00",
    ),
    dict(
        name="disapplied",
        description="This guideline is advisory, should be followed when able",
        color="#FFCC00",
    ),
]

needs_decidabilities = [
    dict(
        name="decidable",
        description="This guideline can be automatically checked with tooling",
        color="#999999",
    ),
    dict(
        name="undecidable",
        description="This guideline cannot be automatically checked with tooling",
        color="#999999",
    ),
]

needs_scopes = [
    dict(
        name="module",
        description="This guideline can be checked at the module level",
        color="#999999",
    ),
    dict(
        name="crate",
        description="This guideline can be checked at the crate level",
        color="#FFCC00",
    ),
    dict(
        name="system",
        description="This guideline must be checked alongside the entire source",
        color="#FFCC00",
    ),
]

needs_releases = [
    dict(
        name="1.85.0",
        description="This guideline can be checked at the module level",
        color="#999999",
    ),
    dict(
        name="1.85.1",
        description="This guideline can be checked at the module level",
        color="#999999",
    ),
]

# Enable needs export
needs_extra_options = [
    "category",
    "recommendation",
    "fls",
    "decidability",
    "scope",
    "release",
]


# Required guideline fields
required_guideline_fields = [
    "category",
    "release",
    "fls",
    "decidability",
    "scope",
    "tags",
]  # Id is automatically generated

# -- Bibliography validation configuration -----------------------------------

# Enable URL validation (typically only in CI)
bibliography_check_urls = False  # Set via --define or environment

# Timeout for URL checks in seconds
bibliography_url_timeout = 10

# Whether broken URLs should fail the build (True) or just warn (False)
bibliography_fail_on_broken = True

# Whether duplicate URLs should fail the build
bibliography_fail_on_duplicates = True

# Whether to warn about bibliography entries not cited in text
bibliography_check_unused = False

# -- Text content validation configuration -----------------------------------

# Enable inline URL detection in guideline text
# When enabled, URLs in guideline content will be flagged as errors
# Contributors should use :std: role or bibliography citations instead
text_check_inline_urls = True

# Whether inline URLs should fail the build (True) or just warn (False)
text_check_fail_on_inline_urls = True

# -- Options for HTML output -------------------------------------------------

# Configure the theme
html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
templates_path = ['_templates']

# Custom CSS files to include
html_css_files = [
    'custom.css',
]
