.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

###############
Style Guideline
###############

******************************
Specifying requirements levels
******************************

We follow `IETF RFC 2119 <https://datatracker.ietf.org/doc/html/rfc2119>`_
for specifying requirements levels.

*****************************
Example of a coding guideline
*****************************

Below is an example of a coding guideline.

We will examine each part:

* ``guideline``
* ``rationale``
* ``non_compliant_example``
* ``compliant_example``
* ``bibliography``

::

   .. guideline:: Do not use an integer type as a divisor during integer division
      :id: gui_7y0GAMmtMhch
      :category: advisory
      :status: draft
      :release: latest
      :fls: fls_Q9dhNiICGIfr
      :decidability: decidable
      :scope: module
      :tags: numerics, subset

      Do not provide a right operand of integer type :cite:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
      during a division expression :cite:`gui_7y0GAMmtMhch:FLS-DIVISION-EXPR` or remainder
      expression :cite:`gui_7y0GAMmtMhch:FLS-REMAINDER-EXPR` when the left operand also has
      integer type.

      .. rationale::
         :id: rat_vLFlPWSCHRje
         :status: draft

         Integer division and integer remainder division both panic when the right operand
         has a value of zero. Division by zero is undefined in mathematics because it leads
         to contradictions and there is no consistent value that can be assigned as its result.

      .. non_compliant_example::
         :id: non_compl_ex_0XeioBrgfh5z
         :status: draft

         Both the division and remainder operations in this non-compliant example will panic
         if evaluated because the right operand is zero.

         .. rust-example::
             :compile_fail:

             fn main() {
                 let x = 0;
                 let _y = 5 / x; // This line will panic.
                 let _z = 5 % x; // This line would also panic.
             }

      .. compliant_example::
         :id: compl_ex_k1CD6xoZxhXb
         :status: draft

         Checked division prevents division by zero from occurring.
         The programmer can then handle the returned :std:`std::option::Option`.

         .. rust-example::

            fn main() {
                // Using the checked division API
                let _y = match 5i32.checked_div(0) {
                    None => 0,
                    Some(r) => r,
                };

                // Using the checked remainder API
                let _z = match 5i32.checked_rem(0) {
                    None => 0,
                    Some(r) => r,
                };
            }

      .. compliant_example::
         :id: compl_ex_k1CD6xoZxhXc
         :status: draft

         This compliant solution creates a divisor using :std:`std::num::NonZero`.

         .. rust-example::
            :version: 1.79

            use std::num::NonZero;

            fn main() {
                let x = 0u32;
                if let Some(divisor) = NonZero::<u32>::new(x) {
                    let _result = 5u32 / divisor;
                }
            }

      .. bibliography::
         :id: bib_7y0GAMmtMhch
         :status: draft

         .. list-table::
            :header-rows: 0
            :widths: auto
            :class: bibliography-table

            * - :bibentry:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
              - The Rust FLS. "Types and Traits - Integer Types." https://rust-lang.github.io/fls/types-and-traits.html#integer-types
            * - :bibentry:`gui_7y0GAMmtMhch:FLS-DIVISION-EXPR`
              - The Rust FLS. "Expressions - Syntax - DivisionExpression." https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression
            * - :bibentry:`gui_7y0GAMmtMhch:FLS-REMAINDER-EXPR`
              - The Rust FLS. "Expressions - Syntax - RemainderExpression." https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression

``guideline``
=============

::

   .. guideline:: Do not use an integer type as a divisor during integer division
      :id: gui_7y0GAMmtMhch
      :category: advisory
      :status: draft
      :release: latest
      :fls: fls_Q9dhNiICGIfr
      :decidability: decidable
      :scope: module
      :tags: numerics, subset

``guideline`` Title
-------------------

The Title **MUST** provide a description of the guideline.

``guideline`` ``id``
--------------------

A unique identifier for each guideline. Guideline identifiers **MUST** begin with ``gui_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate_guideline_templates.py`` script to ensure
compliance.

``category``
------------

**MUST** be one of these values:

* ``mandatory``
* ``required``
* ``advisory``
* ``disapplied``

``mandatory``
^^^^^^^^^^^^^

Code claimed to be in compliance with this document **MUST** follow every guideline marked as ``mandatory``.

*TODO(pete.levasseur): Add more tips on when this is a good choice for a guideline.*

``required``
^^^^^^^^^^^^

Code claimed to be in compliance with this document **MUST** follow every guideline marked as ``required``,
with a formal deviation required as outlined in :ref:`Compliance`, where this is not the case.

An organization or project **MAY** choose to recategorize any ``required`` guideline to ``mandatory``.

*TODO(pete.levasseur): Add more tips on when this is a good choice for a guideline.*

``advisory``
^^^^^^^^^^^^

These are recommendations and **SHOULD** be applied. However, the category of ``advisory`` does not mean
that these items can be ignored, but rather that they **SHOULD** be followed as far as reasonably practical.
Formal deviation is not necessary for advisory guidelines but, if the formal deviation process is not followed,
alternative arrangements **MUST** be made for documenting non-compliances.

An organization or project **MAY** choose to recategorize any ``advisory`` guideline as ``mandatory``
or ``required``, or as ``disapplied``.

If contributing a guideline, you **MAY** choose to submit it as ``advisory``
and ask for support in assigning the guideline the correct category.

*TODO(pete.levasseur): Add more tips on when this is a good choice for a guideline.*

``disapplied``
^^^^^^^^^^^^^^

These are guidelines for which no enforcement is expected and any non-compliance **MAY** be disregarded.

Where a guideline does not apply to the chosen release of the Rust compiler, it **MUST** be treated
as ``disapplied`` for the purposes of coding guideline :ref:`Compliance`.

An organization or project **MAY** choose to recategorize any ``disapplied`` guideline as ``mandatory``
or ``required``, or as ``advisory``.

*Note*: Rather than changing the categorization of a guideline to ``disapplied`` when we wish to
make it not applicable, we **MUST** instead leave the categorization as-is and instead change
the ``status`` to ``retired``.

*TODO(pete.levasseur): Add more tips on when this is a good choice for a guideline.*

``guideline`` ``status``
------------------------

**MUST** be one of these values:

* ``draft``
* ``approved``
* ``retired``

Guidelines have a lifecycle. When they are first proposed and **MUST** be marked as ``draft``
to allow adoption and feedback to accrue. The Coding Guidelines Subcommittee **MUST**
periodically review ``draft`` guidelines and either promote them to ``approved``
or demote them to ``retired``.

From time to time an ``approved`` guideline **MAY** be moved to ``retired``. There
could be a number of reasons, such as: a guideline which was a poor fit or wrong,
or in order to make a single guideline more granular and replace it with
more than one guideline.

For more, see :ref:`Guideline Lifecycle`.

``draft``
^^^^^^^^^

These guidelines are not yet considered in force, but are mature enough they **MAY** be enforced.
No formal deviation is required as outlined in :ref:`Compliance`, but alternative arrangements
**MUST** be made for documenting non-compliances.

*Note*: ``draft`` guideline usage and feedback will help to either promote them to ``approved`` or demote
them to ``retired``.

``approved``
^^^^^^^^^^^^

These guidelines **MUST** be enforced. Any deviations **MUST** follow the rule for their
appropriate ``category``.

``retired``
^^^^^^^^^^^^^^

These are guidelines for which no enforcement is expected and any non-compliance **MAY** be disregarded.

*Note*: The ``retired`` ``status`` supersedes any ``category`` assigned a guideline, effectively
conferring upon the guideline the ``category`` of ``disapplied`` with no ability to recategorize it
to ``mandatory``, ``required``, or ``advisory``. The ``category`` assigned the guideline at the time
it is retired is kept.

``release``
------------------------

Each guideline **MUST** note the Rust compiler releases to which the guideline is applicable.

A guideline likely **MAY** apply to more than one release.

If a guideline applies to more than one release, the list **MUST** be semicolon separated.

``fls``
-------

Each guideline **MUST** have linkage to an appropriate ``paragraph-id`` from the
Ferrocene Language Specification (FLS). That linkage to the FLS is the means by which
the guidelines cover exactly the specification, no more and no less.

A single FLS ``paragraph-id`` **MAY** have more than one guideline which applies to it.

``decidability``
----------------

**MUST** be one of these values:

* ``decidable``
* ``undecidable``

``decidability`` describes the theoretical ability of a static analyzer to answer the
question: "Does this code comply with this rule?"

A guideline **MUST** be classified as  ``decidable`` if it is possible for such a static
analyzer to answer the question with "yes" or "no" in *every case* and **MUST** be classified
as ``undecidable`` otherwise.


``scope``
---------

**MUST** be one of these values:

* ``module``
* ``crate``
* ``system``

The ``scope`` describes at which level of program scope the guideline can be confirmed followed
for each instance of code for which a guideline applies.

For example, if there for each instance of ``unsafe`` code usage there may be guidelines which
must then be checked at the module level. This must be done since if a single usage of ``unsafe``
is used in a module, the entire module must be checked for certain invariants.

When writing guidelines we **MUST** attempt to lower the ``scope`` as small as possible and as
allowed by the semantics to improve tractability of their application.

``module``
^^^^^^^^^^

A guideline which is able to be checked at the module level without reference
to other modules or crates **MUST** be classified as ``module``.

``crate``
^^^^^^^^^

A guideline which cannot be checked at the module level, but which does not require the
entire source text **MUST** be classified as ``crate``.

``system``
^^^^^^^^^^

A guideline which cannot be checked at the module or crate level and requires the entire
source text **MUST** be classified as ``system``.


``tags``
--------

The ``tags`` are largely descriptive, not prescriptive means of finding commonality between
similar guidelines.

Each guideline **MUST** have at least one item listed in ``tags``.

Guideline Content
-----------------

Each ``guideline`` **MUST** have content which follows the options to give an overview of
what it covers.

Content **SHOULD** aim to be as short and self-contained as possible, while still explaining
the scope of the guideline.

Guideline content consists of an Amplification and any Exceptions, which are normative,
supported by a Rationale and examples, which are not normative.
The justification extended explanation for the guideline **SHOULD** appear in the non-normative
Rationale rather than in the normative content.

Amplification
^^^^^^^^^^^^^

The *Amplification* is the block of text that **MAY** appear immediately below the guideline
attribute block, before any other subheadings.
If it is provided, the Amplification is normative; if it conflicts with the ``guideline`` Title,
the Amplification **MUST** take precedence. This mechanism is convenient as it allows a complicated
concept to be conveyed using a short Title and refined by the text below.

Content in the Amplification **SHOULD NOT** cover the rationale for the guideline or any
non-normative explanations, which **SHOULD** be provided in the ``rationale`` and examples sections
where helpful.

The Amplification **MAY** contain citations to the bibliography using the ``:cite:`` role
(see `Citation Roles`_ below).

::

      Do not provide a right operand of integer type :cite:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
      during a division expression :cite:`gui_7y0GAMmtMhch:FLS-DIVISION-EXPR` or remainder
      expression :cite:`gui_7y0GAMmtMhch:FLS-REMAINDER-EXPR` when the left operand also has
      integer type.

Exception
^^^^^^^^^

Guideline Content **MAY** contain a section titled *Exception* followed by text that that describes
situations in which the guideline does not apply. The use of exceptions permits the description of
some guidelines to be simplified. It is important to note that an exception is a situation in which
a guideline does not apply. Code that complies with a guideline by virtue of an exception does not
require a deviation.

If it is provided, the Exception is normative; if it conflicts with the ``guideline`` Title or the
Amplification, the Exception takes precedence over both. Depending on the individual guideline, it
may be clearer to have an Amplification or Title with an explicit Exception overriding parts of
their description, or it may be clearer to express excepted cases as integrated sentences in the
Amplification. This decision is editorial.

``rationale``
=============

Each Guideline **MUST** provide a *Rationale* for its inclusion and enforcement.

::

      .. rationale::
         :id: rat_vLFlPWSCHRje
         :status: draft

         Integer division and integer remainder division both panic when the right operand
         has a value of zero. Division by zero is undefined in mathematics because it leads
         to contradictions and there is no consistent value that can be assigned as its result.

``rationale`` ``id``
--------------------

A unique identifier for each rationale. Rationale identifiers **MUST** begin with ``rat_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate_guideline_templates.py`` script to ensure
compliance.

``rationale`` ``status``
------------------------

The ``status`` option of a ``rationale`` **MUST** match the ``status`` of its parent ``guideline``.

Rationale Content
-----------------

The content of the rationale **SHOULD** provide the relevant context for why this guideline is useful.
The Rationale **SHOULD** make reference to any undefined behaviors or known errors associated
with the subject of the guideline.
The Rationale **MAY** make reference to other guidelines or to external documents cited in the
References.

The Rationale **SHOULD** be supported by code examples wherever concise examples are possible.

``non_compliant_example``
=========================

::

      .. non_compliant_example::
         :id: non_compl_ex_0XeioBrgfh5z
         :status: draft

         Both the division and remainder operations in this non-compliant example will panic
         if evaluated because the right operand is zero.

         .. rust-example::
             :compile_fail:

             fn main() {
                 let x = 0;
                 let _y = 5 / x; // This line will panic.
                 let _z = 5 % x; // This line would also panic.
             }

``non_compliant_example`` ``id``
--------------------------------

A unique identifier for each ``non_compliant_example``. ``non_compliant_example`` identifiers
**MUST** begin with ``non_compl_ex_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate_guideline_templates.py`` script to ensure
compliance.

``non_compliant_example`` ``status``
------------------------------------

The ``status`` option of a ``non_compl_ex`` **MUST** match the ``status`` of its parent ``guideline``.

``non_compliant_example`` Content
---------------------------------

The Content section of a ``non_compliant_example`` **MUST** contain both a Code Explanation and Code Example.

The ``non_compliant_example`` is neither normative, nor exhaustive. ``guideline`` Content **MUST** take precedence.

``non_compliant_example`` Code Explanation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Code Explanation of a ``non_compliant_example`` **MUST** explain in prose the reason the guideline
when not applied results in code which is undesirable.

The Code Explanation of a ``non_compliant_example`` **MAY** be a simple explanation no longer than
a sentence.

The Code Explanation of a ``non_compliant_example`` **SHOULD** be no longer than necessary to explain
the Code Example that follows.

``non_compliant_example`` Code Example
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``non_compliant_example`` Code Example **MUST** use the ``.. rust-example::`` directive
(see `The rust-example Directive`_ below).

A ``non_compliant_example`` Code Example **SHOULD** be made as short and simple to understand
as possible.

A ``non_compliant_example`` Code Example **SHOULD** include clarifying comments if complex and/or
long.

The Code Example of a ``non_compliant_example`` **MUST NOT** contain a guideline violation other
than the current guideline.

``compliant_example``
=====================

A compliant example **SHOULD** be omitted when the guideline forbids an action entirely, i.e. there
is no compliant way to achieve the goal of the non-compliant code, rather than giving an irrelevant
example (or encouraging strange workarounds).
When there is a clear and idiomatic compliant way to achieve the goal, a compliant example **SHOULD**
be provided after the corresponding non-compliant example.

::

      .. compliant_example::
         :id: compl_ex_k1CD6xoZxhXb
         :status: draft

         Checked division prevents division by zero from occurring.
         The programmer can then handle the returned :std:`std::option::Option`.

         .. rust-example::

            fn main() {
                // Using the checked division API
                let _y = match 5i32.checked_div(0) {
                    None => 0,
                    Some(r) => r,
                };

                // Using the checked remainder API
                let _z = match 5i32.checked_rem(0) {
                    None => 0,
                    Some(r) => r,
                };
            }

``compliant_example`` ``id``
----------------------------

A unique identifier for each ``compliant_example``. ``compliant_example`` identifiers
**MUST** begin with ``compl_ex_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate_guideline_templates.py`` script to ensure
compliance.

``compliant_example`` ``status``
--------------------------------

The ``status`` option of a ``compl_ex`` **MUST** match the ``status`` of its parent ``guideline``.

``compliant_example`` Content
-----------------------------

The Content section of a ``compliant_example`` **MUST** contain both a Code Explanation and Code Example.

The ``compliant_example`` is neither normative, nor exhaustive. ``guideline`` Content **MUST** take precedence.

``compliant_example`` Code Explanation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Code Explanation of a `compliant_example` **MAY** be a simple explanation no longer than
a sentence.

The Code Explanation of a ``compliant_example`` **SHOULD** be no longer than necessary to explain
the Code Example that follows.


``compliant_example`` Code Example
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``compliant_example`` Code Example **MUST** use the ``.. rust-example::`` directive
(see `The rust-example Directive`_ below).

A ``compliant_example`` Code Example **SHOULD** be made as short and simple to understand
as possible.

A ``compliant_example`` Code Example **SHOULD** include clarifying comments if complex and/or
long.

A ``compliant_example`` Code Example **MUST** comply with every guideline.

A ``compliant_example`` Code Example **SHOULD** try to illustrate the guideline by
getting close to violating it, but staying within compliance.

``bibliography``
================

Each ``guideline`` **SHOULD** have an associated ``bibliography`` if it references external
documents or specifications. The bibliography provides a structured way to cite sources
and enables readers to navigate directly to referenced materials.

::

      .. bibliography::
         :id: bib_7y0GAMmtMhch
         :status: draft

         .. list-table::
            :header-rows: 0
            :widths: auto
            :class: bibliography-table

            * - :bibentry:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
              - The Rust FLS. "Types and Traits - Integer Types." https://rust-lang.github.io/fls/types-and-traits.html#integer-types
            * - :bibentry:`gui_7y0GAMmtMhch:FLS-DIVISION-EXPR`
              - The Rust FLS. "Expressions - Syntax - DivisionExpression." https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression
            * - :bibentry:`gui_7y0GAMmtMhch:FLS-REMAINDER-EXPR`
              - The Rust FLS. "Expressions - Syntax - RemainderExpression." https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression

``bibliography`` ``id``
-----------------------

A unique identifier for each ``bibliography``. ``bibliography`` identifiers
**MUST** begin with ``bib_``.

The suffix after ``bib_`` **SHOULD** match the guideline's ID suffix (e.g., ``bib_7y0GAMmtMhch``
for guideline ``gui_7y0GAMmtMhch``).

``bibliography`` ``status``
---------------------------

The ``status`` option of a ``bibliography`` **MUST** match the ``status`` of its parent ``guideline``.

``bibliography`` Content
------------------------

The bibliography **MUST** be formatted as a ``list-table`` with no header rows and the
``bibliography-table`` class for proper styling.

Each row **MUST** contain two columns:

1. The citation anchor using the ``:bibentry:`` role
2. The citation description including author, title, and URL

Bibliography Validation
^^^^^^^^^^^^^^^^^^^^^^^

The build system validates bibliography entries for:

* **Citation key format** - Keys **MUST** be ``UPPERCASE-WITH-HYPHENS`` (e.g., ``FLS-INTEGER-TYPES``, ``CERT-C-INT34``)
* **Guideline ID matching** - The guideline ID in ``:bibentry:`` roles **MUST** match the containing guideline
* **URL consistency** - The same URL used across different guidelines **MUST** use identical citation keys and descriptions
* **Citation references** - All ``:cite:`` references **MUST** have corresponding ``:bibentry:`` definitions

*****************************
Citation Roles
*****************************

The documentation system provides two roles for managing citations: ``:cite:`` for referencing
citations in text, and ``:bibentry:`` for defining citation anchors in bibliographies.

``:cite:`` Role
===============

The ``:cite:`` role creates a clickable reference in the guideline text that links to the
corresponding bibliography entry.

**Syntax:** ``:cite:`gui_GUIDELINE_ID:CITATION-KEY```

**Example:**

::

   As documented in :cite:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`, integer types have
   specific behaviors during division operations.

This renders as ``[FLS-INTEGER-TYPES]`` and links to the bibliography entry.

The guideline ID prefix (``gui_7y0GAMmtMhch:``) **MUST** match the ID of the guideline
containing the citation. This ensures citations are properly namespaced and validated
during the build.

``:bibentry:`` Role
===================

The ``:bibentry:`` role creates an anchor in the bibliography table that ``:cite:`` references
can link to.

**Syntax:** ``:bibentry:`gui_GUIDELINE_ID:CITATION-KEY```

**Example:**

::

   * - :bibentry:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
     - The Rust FLS. "Types and Traits - Integer Types." https://rust-lang.github.io/fls/...

This renders as ``[FLS-INTEGER-TYPES] ↩`` with a back-navigation button that returns
the reader to the citation in the text.

Citation Key Format
===================

Citation keys **MUST** follow this format:

* Start with an uppercase letter
* Contain only uppercase letters, numbers, and hyphens
* End with an uppercase letter or number
* Maximum 50 characters

**Valid examples:**

* ``FLS-INTEGER-TYPES``
* ``RUST-REF-UNION``
* ``CERT-C-INT34``
* ``ISO-26262-2018``

**Invalid examples:**

* ``fls-integer-types`` (lowercase)
* ``123-KEY`` (starts with number)
* ``KEY_WITH_UNDERSCORE`` (contains underscore)

*****************************
The rust-example Directive
*****************************

All Rust code examples in guidelines **MUST** use the ``.. rust-example::`` directive
instead of ``.. code-block:: rust``. This directive provides:

* Interactive execution via the Rust Playground
* Copy-to-clipboard functionality
* Miri integration for undefined behavior detection
* Build-time validation of code examples
* Support for hidden lines

Basic Usage
===========

::

   .. rust-example::

      fn main() {
          println!("Hello, world!");
      }

This creates an interactive code block with copy, run, and toggle buttons.

Rustdoc Attributes
==================

The directive supports standard rustdoc attributes that control how examples are compiled and run.

``:ignore:``
------------

The example is not compiled or tested. Use for illustrative code that is intentionally incomplete.

::

   .. rust-example::
      :ignore:

      // This code is for illustration only
      fn hypothetical_feature() { ... }

``:compile_fail:``
------------------

The example **SHOULD** fail to compile. Optionally specify an expected error code.

::

   .. rust-example::
      :compile_fail: E0277

      fn example() {
          let x: i32 = "string"; // Type mismatch
      }

``:should_panic:``
------------------

The example **SHOULD** compile but panic at runtime.

::

   .. rust-example::
      :should_panic:

      fn main() {
          panic!("This is expected");
      }

``:no_run:``
------------

The example is compiled but not executed. Use for code that requires specific
runtime conditions or has side effects.

::

   .. rust-example::
      :no_run:

      fn main() {
          std::process::exit(1);
      }

Miri Integration
================

The ``:miri:`` option enables Miri checking for undefined behavior detection.
Examples containing ``unsafe`` code **MUST** include a ``:miri:`` option.

``:miri:`` (default: check)
---------------------------

Run Miri and expect no undefined behavior.

::

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
--------------------

Run Miri and expect undefined behavior to be detected. Use when demonstrating
what *not* to do.

::

   .. rust-example::
      :miri: expect_ub

      fn main() {
          unsafe {
              let ptr: *const i32 = std::ptr::null();
              let _ = *ptr; // UB: null pointer dereference
          }
      }

``:miri: skip``
---------------

Skip Miri checking. Use when Miri does not support the operations in the example.
The reason for skipping **SHOULD** be documented in the surrounding prose.

::

   .. rust-example::
      :miri: skip

      // Miri doesn't support this FFI operation
      fn main() {
          unsafe { /* FFI call */ }
      }

*Note:* ``:miri:`` cannot be combined with ``:ignore:``, ``:compile_fail:``, or ``:no_run:``
because Miri requires code that compiles and runs.

Warning Handling
================

The ``:warn:`` option controls how compiler warnings are treated.

``:warn:`` or ``:warn: error``
------------------------------

Fail on compiler warnings. This is the default when ``rust_examples_fail_on_warnings = True``
in the configuration.

``:warn: allow``
----------------

Allow compiler warnings without failing.

::

   .. rust-example::
      :warn: allow

      fn main() {
          let x = 42; // Warning: unused variable (allowed)
      }

Toolchain Options
=================

``:edition:``
-------------

Specify the Rust edition. Default is ``2021``.

::

   .. rust-example::
      :edition: 2018

      // Edition 2018 specific code

``:channel:``
-------------

Specify the release channel: ``stable``, ``beta``, or ``nightly``.

::

   .. rust-example::
      :channel: nightly

      #![feature(some_nightly_feature)]

``:version:``
-------------

Specify a target Rust version. A badge appears if the version differs
significantly from the configured default.

::

   .. rust-example::
      :version: 1.79

      use std::num::NonZero;

      fn main() {
          // Code using features from Rust 1.79
      }

Hidden Lines
============

Lines prefixed with ``# `` (hash-space) are hidden by default but included
when compiling and running the code. This allows showing only the relevant
parts of an example while maintaining compilability.

::

   .. rust-example::

      # use std::collections::HashMap;
      # fn main() {
      let mut map = HashMap::new();
      map.insert("key", "value");
      # }

The hidden lines can be revealed using the toggle button (eye icon) in the
rendered output.

Hidden lines **SHOULD** be used for:

* Boilerplate imports
* ``fn main() {}`` wrappers
* Setup code that distracts from the example's purpose
* ``#[allow(dead_code)]`` and similar attributes

Display Options
===============

``:show_hidden:``
-----------------

Show hidden lines by default instead of hiding them.

``:name:``
----------

Assign a name to the example for reference purposes.

*****************************
Standard Library Links
*****************************

The ``:std:`` role creates links to Rust standard library documentation.

**Syntax:** ``:std:`path::to::Item```

**Examples:**

::

   The type needs to implement :std:`core::marker::Copy`.

   See :std:`std::option::Option` for the return type.

   Use :std:`std::num::NonZero` for guaranteed non-zero values.

The role generates a link to the Rust documentation search with the provided path.
This **SHOULD** be used instead of inline URLs to standard library documentation.

*****************************
Build-Time Validation
*****************************

The build system performs several validations to ensure guideline quality:

Required Fields
===============

Each guideline **MUST** have the following fields populated:

* ``category``
* ``release``
* ``fls``
* ``decidability``
* ``scope``
* ``tags``

Required Child Elements
=======================

Each guideline **MUST** have the following child elements:

* ``rationale``
* ``non_compliant_example``
* ``compliant_example``

The ``bibliography`` is **OPTIONAL** but **SHOULD** be included when external
sources are referenced.

Inline URL Detection
====================

The build system detects inline URLs in guideline text and flags them as errors.
URLs **MUST NOT** appear directly in guideline content. Instead:

* For Rust standard library documentation, use the ``:std:`` role
* For external references, add them to the ``bibliography`` and use ``:cite:``

**Non-compliant:**

::

   See https://doc.rust-lang.org/std/num/struct.Wrapping.html for details.

**Compliant:**

::

   See :std:`std::num::Wrapping` for details.

Or for external sources:

::

   As documented in :cite:`gui_MyGuideline:SOURCE-NAME`, ...
