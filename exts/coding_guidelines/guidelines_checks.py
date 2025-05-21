# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from sphinx.errors import SphinxError
from sphinx_needs.data import SphinxNeedsData
from .common import logger, get_tqdm, bar_format 


class IntegrityCheckError(SphinxError):
    category = "Integrity Check Error"

def validate_required_fields(app, env):
    """
    Validate the required fields defined in conf.py 
    """
    logger.debug("Validating required fields")
    data = SphinxNeedsData(env)
    needs = data.get_needs_view()

    required_fields = app.config.required_guideline_fields  # Access the configured values

    # prefiltering: this is mainly done for tqdm progress
    guidelines = {k: v for k, v in needs.items() if v.get('type') == 'guideline'}
    pbar = get_tqdm(iterable=guidelines.items(), desc="Checking for required fields", bar_format=bar_format, unit="need")

    for key, value in pbar:
        if value.get('type') == 'guideline':
            missing_fields = []
            for field in required_fields:
                pbar.set_postfix(field=field if field is not None else "Missing")
                if value.get(field) in  (None, '', []):
                    missing_fields.append(field)


            if missing_fields:
                error_message = (
                    f"Guideline '{value.get('title')}' (ID: {value.get('id')}) "
                    f"in {value.get('docname')}:{value.get('lineno')} is missing the following required fields: "
                    f"{', '.join(missing_fields)}"
                )
                logger.error(error_message)
                app.builder.statuscode = 1 # mark the build as failed (0 means success)
                raise IntegrityCheckError(error_message) 
