.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

==================================
Coding Guidelines Sphinx Extension
==================================

To enhance the Safety-Critical Rust Coding Guidelines, and to facilitate its
authoring, updating, and testing it easier, we developed and use a custom
Sphinx extension that adds new roles and directives. The source code of the
extension is in the ``exts/coding_guidelines`` directory.

.. contents:: In this document:

Ferrocene Language Specification Conformance
============================================

Various checks are performed against the ``:fls:`` option present in ``guideline`` directives to
ensure they are valid.

Coverage of the coding guidelines over the FLS is calculated.

Each coding guideline has its ``:fls:`` option turned into a hyperlink to the corresponding element
within the FLS to be able to navigate there directly.

Further an ``spec.lock`` file located at ``root/src/spec.lock`` is validated against the currently
deployed version of the Ferrocene Language Spec and the build is failed if there is discrepancy.

Links to the Rust Standard Library
==================================

You can link to the documentation of items defined in the Rust standard library
(``core``, ``alloc``, ``std``, ``test`` and ``proc_macro``) by using the
``:std:`type``` role (even for types defined in other standard library crates)
with the fully qualified item path:

.. code-block:: rst

   The type needs to implement :std:`core::marker::Copy`.

The role generates a link to the Rust documentation search with the provided path.

Bibliography and Citations
==========================

The extension provides a bibliography system for managing references in guidelines.
Each guideline can have its own bibliography section with proper citation linking.

Citation Roles
--------------

Two roles are provided for linking citations:

``:cite:`` Role
~~~~~~~~~~~~~~~

Creates a clickable reference in guideline text that links to the bibliography entry.

**Syntax:** ``:cite:`gui_GuidelineId:CITATION-KEY```

**Example:**

.. code-block:: rst

   As documented in :cite:`gui_Abc123XyzQrs:RUST-REF-UNION`, unions have
   specific safety requirements.

This renders as ``[RUST-REF-UNION]`` and links to the corresponding bibliography entry.

``:bibentry:`` Role
~~~~~~~~~~~~~~~~~~~

Creates an anchor in the bibliography table for the citation.

**Syntax:** ``:bibentry:`gui_GuidelineId:CITATION-KEY```

**Example:**

.. code-block:: rst

   .. bibliography::
      :id: bib_Abc123XyzQrs

      .. list-table::
         :header-rows: 0

         * - :bibentry:`gui_Abc123XyzQrs:RUST-REF-UNION`
           - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html

This renders as ``[RUST-REF-UNION] ↩`` with a back-navigation button.

Citation Key Format
~~~~~~~~~~~~~~~~~~~

Citation keys must follow this format:

- Start with an uppercase letter
- Contain only uppercase letters, numbers, and hyphens
- End with an uppercase letter or number
- Maximum 50 characters

**Valid examples:** ``RUST-REF-UNION``, ``ISO-26262``, ``CERT-C-2016``

**Invalid examples:** ``rust-ref``, ``123-KEY``, ``KEY_WITH_UNDERSCORE``

Bibliography Validation
-----------------------

The extension validates bibliography entries during the build:

1. **Citation key format** - Keys must match the required format
2. **Guideline ID matching** - The guideline ID in roles must match the containing guideline
3. **URL consistency** - Same URLs across guidelines must use identical citation keys and descriptions
4. **Citation references** - Referenced citations must exist in the bibliography
5. **Unused citations** (optional) - Bibliography entries not cited in text can warn when enabled
6. **URL accessibility** (optional) - URLs can be checked for validity

Configuration Options
~~~~~~~~~~~~~~~~~~~~~

In ``conf.py``:

.. code-block:: python

   bibliography_check_urls = False           # Enable URL validation (default: False)
   bibliography_url_timeout = 10             # Timeout in seconds for URL checks
   bibliography_fail_on_broken = True        # Error vs warning for broken URLs
   bibliography_fail_on_inconsistent = True  # Error vs warning for inconsistent entries
   bibliography_check_unused = False         # Warn on uncited bibliography entries

Interactive Rust Examples
=========================

The ``rust-example`` directive provides interactive code examples with rustdoc-style
attributes, Rust Playground integration, and Miri support for undefined behavior detection.

Basic Usage
-----------

.. code-block:: rst

   .. rust-example::

      fn main() {
          println!("Hello, world!");
      }

This creates an interactive code block with copy, run, and toggle buttons.

Rustdoc Attributes
------------------

The directive supports standard rustdoc attributes:

``:ignore:``
~~~~~~~~~~~~

The example is not compiled or tested.

.. code-block:: rst

   .. rust-example::
      :ignore:

      // This code is for illustration only
      fn hypothetical_feature() { ... }

``:compile_fail:``
~~~~~~~~~~~~~~~~~~

The example should fail to compile. Optionally specify an expected error code.

.. code-block:: rst

   .. rust-example::
      :compile_fail: E0277

      fn example() {
          let x: i32 = "string"; // Type mismatch
      }

``:should_panic:``
~~~~~~~~~~~~~~~~~~

The example should compile but panic at runtime.

.. code-block:: rst

   .. rust-example::
      :should_panic:

      fn main() {
          panic!("This is expected");
      }

``:no_run:``
~~~~~~~~~~~~

The example is compiled but not executed.

.. code-block:: rst

   .. rust-example::
      :no_run:

      fn main() {
          // Code that requires specific environment
          std::process::exit(1);
      }

Miri Integration
----------------

The ``:miri:`` option enables Miri checking for undefined behavior detection.
This is **required** for examples containing ``unsafe`` code (configurable).

``:miri:`` (or ``:miri: check``)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run Miri and expect no undefined behavior.

.. code-block:: rst

   .. rust-example::
      :miri:

      fn main() {
          unsafe {
              let x: i32 = 42;
              let ptr = &x as *const i32;
              println!("{}", *ptr); // Safe: valid pointer
          }
      }

``:miri: expect_ub``
~~~~~~~~~~~~~~~~~~~~

Run Miri and expect undefined behavior to be detected.

.. code-block:: rst

   .. rust-example::
      :miri: expect_ub

      fn main() {
          unsafe {
              let ptr: *const i32 = std::ptr::null();
              let _ = *ptr; // UB: null pointer dereference
          }
      }

``:miri: skip``
~~~~~~~~~~~~~~~

Skip Miri checking (document the reason in prose).

.. code-block:: rst

   .. rust-example::
      :miri: skip

      // Miri doesn't support this FFI operation
      fn main() {
          unsafe { some_ffi_function(); }
      }

**Note:** Miri cannot be combined with ``:ignore:``, ``:compile_fail:``, or ``:no_run:``
since Miri requires code that compiles and runs.

Warning Handling
----------------

The ``:warn:`` option controls how compiler warnings are treated.

``:warn:`` or ``:warn: error``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Fail on compiler warnings (this is the default when ``rust_examples_fail_on_warnings = True``).

.. code-block:: rst

   .. rust-example::
      :warn: error

      fn main() {
          let x = 42; // Warning: unused variable
      }

``:warn: allow``
~~~~~~~~~~~~~~~~

Allow compiler warnings without failing.

.. code-block:: rst

   .. rust-example::
      :warn: allow

      fn main() {
          let x = 42; // Warning allowed
      }

Toolchain Options
-----------------

``:edition:``
~~~~~~~~~~~~~

Specify the Rust edition (default from config, typically ``2021``).

.. code-block:: rst

   .. rust-example::
      :edition: 2018

      // Edition 2018 specific code

``:channel:``
~~~~~~~~~~~~~

Specify the release channel: ``stable``, ``beta``, or ``nightly``.

.. code-block:: rst

   .. rust-example::
      :channel: nightly

      #![feature(some_nightly_feature)]

``:version:``
~~~~~~~~~~~~~

Specify a target Rust version. A badge appears if the version differs
significantly from the configured default.

.. code-block:: rst

   .. rust-example::
      :version: 1.79.0

      // Code targeting Rust 1.79

Hidden Lines
------------

Lines prefixed with ``# `` (hash-space) are hidden by default but included
when running the code. This allows showing only the relevant parts while
maintaining compilable examples.

.. code-block:: rst

   .. rust-example::

      # use std::collections::HashMap;
      # fn main() {
      let mut map = HashMap::new();
      map.insert("key", "value");
      # }

The hidden lines can be revealed using the toggle button in the rendered output.

Display Options
---------------

``:show_hidden:``
~~~~~~~~~~~~~~~~~

Show hidden lines by default.

.. code-block:: rst

   .. rust-example::
      :show_hidden:

      # fn main() {
      println!("Hidden lines visible by default");
      # }

``:name:``
~~~~~~~~~~

Assign a name to the example for reference.

.. code-block:: rst

   .. rust-example::
      :name: my-example

      fn example() {}

Configuration File
------------------

Create ``rust_examples_config.toml`` in your Sphinx source directory:

.. code-block:: toml

   [defaults]
   edition = "2021"
   channel = "stable"
   version = "1.85.0"

   [playground]
   api_url = "https://play.rust-lang.org"

   [warnings]
   version_mismatch_threshold = 2  # Minor versions before showing badge
   fail_on_warnings = true         # Default warning behavior

   [miri]
   require_for_unsafe = true       # Require :miri: for unsafe code
   timeout = 60                    # Miri execution timeout

Configuration in ``conf.py``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   rust_examples_show_hidden = False           # Show hidden lines by default
   rust_examples_require_miri_for_unsafe = True  # Require :miri: for unsafe
   rust_examples_fail_on_warnings = True       # Fail on compiler warnings

Text Validation
===============

The extension validates text content to ensure proper formatting and reference usage.

Inline URL Detection
--------------------

The extension detects inline URLs in guideline content and enforces the use of
proper roles instead:

- **Standard library URLs** should use the ``:std:`` role
- **External reference URLs** should be added to the bibliography and referenced with ``:cite:``

Bibliography entries can include uncited background sources. When
``bibliography_check_unused`` is enabled, uncited entries will emit warnings.

**Example of what NOT to do:**

.. code-block:: rst

   See https://doc.rust-lang.org/std/num/struct.Wrapping.html for details.

**Correct approach:**

.. code-block:: rst

   See :std:`std::num::Wrapping` for details.

Or for external references:

.. code-block:: rst

   As documented in :cite:`gui_MyGuideline:RUST-REF-UNION`, ...

Configuration Options
~~~~~~~~~~~~~~~~~~~~~

In ``conf.py``:

.. code-block:: python

   text_check_inline_urls = True           # Enable inline URL detection
   text_check_fail_on_inline_urls = True   # Error vs warning for inline URLs

Guideline Structure Requirements
================================

Required Fields
---------------

Each guideline must have certain fields populated. The required fields are
configured in ``conf.py``:

.. code-block:: python

   required_guideline_fields = ["release", "fls", "decidability", "scope"]

Missing required fields will cause the build to fail.

Required Child Elements
-----------------------

Each guideline must have associated child elements:

- **rationale** - Explanation of why the guideline exists
- **compliant_example** - Example of code that follows the guideline
- **non_compliant_example** - Example of code that violates the guideline
- **bibliography** (optional) - References for the guideline

The build will fail if any guideline is missing required child elements
(except bibliography, which is optional).

Output Files
============

The extension generates several output files during the build:

``guidelines-ids.json``
-----------------------

A JSON file containing all guidelines with their IDs, checksums, and associated
elements. Used for tracking changes and external tooling integration.

``spec.lock``
-------------

A lock file for the Ferrocene Language Specification, ensuring consistency
between builds and detecting when the FLS changes.

Debug Mode
==========

Enable debug mode in ``conf.py`` to get detailed logging:

.. code-block:: python

   debug = True

This enables verbose logging and disables progress bars for easier debugging.
