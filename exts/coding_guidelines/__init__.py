# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

from sphinx.domains import Domain

from . import (
    common,
    fls_checks,
    fls_linking,
    guidelines_checks,
    std_role,
    write_guidelines_ids,
)
from .common import bar_format, get_tqdm, logger, logging


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


def on_build_finished(app, exception):
    print("\nFinalizing build:")
    for _ in get_tqdm(iterable=range(1), desc="Finalizing", bar_format=bar_format):
        pass

    outdir = app.outdir
    if exception is not None:
        print(" - Build failed")
    else:
        if not app.config.debug:
            print(f" + Build complete -> {outdir}")


def setup(app):
    app.add_domain(CodingGuidelinesDomain)
    app.add_config_value(
        name="offline", default=False, rebuild="env"
    )  # register the offline option
    app.add_config_value(
        name="spec_std_docs_url",
        default="https://doc.rust-lang.org/stable/std",
        rebuild="env",  # Rebuild the environment when this changes
        types=[str],
    )
    app.add_config_value(name="debug", default=False, rebuild="env")
    app.add_config_value(
        name="fls_paragraph_ids_url",
        default="https://rust-lang.github.io/fls/paragraph-ids.json",
        rebuild="env",
    )
    app.add_config_value(
        name="enable_spec_lock_consistency", default=True, rebuild="env"
    )
    app.add_config_value(
        name="required_guideline_fields",
        default=["release", "fls", "decidability", "scope"],
        rebuild="env",
        types=[list],
    )
    if app.config.debug:
        logger.setLevel(logging.INFO)
        common.disable_tqdm = True

    app.connect("env-check-consistency", guidelines_checks.validate_required_fields)
    app.connect("env-check-consistency", fls_checks.check_fls)
    app.connect("build-finished", write_guidelines_ids.build_finished)
    app.connect("build-finished", fls_linking.build_finished)
    app.connect("build-finished", on_build_finished)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
    }
