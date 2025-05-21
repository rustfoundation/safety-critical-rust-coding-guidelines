# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from . import fls_checks
from . import write_guidelines_ids
from . import std_role
from . import fls_linking
from . import guidelines_checks 

from sphinx_needs.api import add_dynamic_function
from sphinx.errors import SphinxError
from sphinx.domains import Domain

import logging

# Get the Sphinx logger
logger = logging.getLogger('sphinx')

class CodingGuidelinesDomain(Domain):
    name = "coding-guidelines"
    label = "Rust Standard Library"
    roles = {
        "std": std_role.StdRefRole(),
    }
    directives = {}
    object_types = {}
    indices = {}
    
    def get_objects(self):
        return []
    
    def merge_domaindata(self, docnames, other):
        pass  # No domain data to merge

def setup(app):
    
    app.add_domain(CodingGuidelinesDomain)
    app.add_config_value(
        name = "offline", 
        default=False, 
        rebuild= "env"
    ) # register the offline option
    app.add_config_value(
        name="spec_std_docs_url",
        default="https://doc.rust-lang.org/stable/std",
        rebuild="env",  # Rebuild the environment when this changes
        types=[str],
    )
    app.add_config_value(name='fls_paragraph_ids_url', 
                         default='https://rust-lang.github.io/fls/paragraph-ids.json', 
                         rebuild='env')
    app.add_config_value(name='enable_spec_lock_consistency',
                         default=True,
                         rebuild='env')
    app.add_config_value(
        name='required_guideline_fields',
        default=['release', 'fls', 'decidability', 'scope'],
        rebuild='env',
        types=[list],
    )

    app.connect('env-check-consistency', guidelines_checks.validate_required_fields)

    app.connect('env-check-consistency', fls_checks.check_fls)

    app.connect('build-finished', write_guidelines_ids.build_finished)

    app.connect('build-finished', fls_linking.build_finished)

    return {
        'version': '0.1',
        'parallel_read_safe': True,
    }
