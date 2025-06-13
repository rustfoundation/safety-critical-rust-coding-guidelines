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

::

   .. guideline:: Avoid Implicit Integer Wrapping
      :id: gui_xztNdXA2oFNB
      :category: required
      :status: draft
      :release: 1.85.0;1.85.1
      :fls: fls_cokwseo3nnr
      :decidability: decidable
      :scope: module
      :tags: numerics

      Code must not rely on Rust's implicit integer wrapping behavior that occurs in release builds.
      Instead, explicitly handle potential overflows using the standard library's checked,
      saturating, or wrapping operations.

      .. rationale::
         :id: rat_kYiIiW8R2qD1
         :status: draft

         In debug builds, Rust performs runtime checks for integer overflow and will panic if detected.
         However, in release builds (with optimizations enabled), integer operations silently wrap
         around on overflow, creating potential for silent failures and security vulnerabilities.

         Safety-critical software requires consistent and predictable behavior across all build
         configurations. Explicit handling of potential overflow conditions improves code clarity,
         maintainability, and reduces the risk of numerical errors in production.

      .. non_compliant_example::
         :id: non_compl_ex_PO5TyFsRTlWv
         :status: draft

          .. code-block:: rust

            fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                // Potential for silent overflow in release builds
                current + velocity
            }

      .. compliant_example::
         :id: compl_ex_WTe7GoPu5Ez0
         :status: draft

          .. code-block:: rust

            fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                // Explicitly handle potential overflow with checked addition
                current.checked_add(velocity).expect("Position calculation overflowed")
            }

``guideline``
=============

::

   .. guideline:: Avoid Implicit Integer Wrapping
      :id: gui_xztNdXA2oFNB
      :category: required
      :status: draft
      :release: 1.85.0;1.85.1
      :fls: fls_cokwseo3nnr
      :decidability: decidable
      :scope: module
      :tags: numerics

      Code must not rely on Rust's implicit integer wrapping behavior that occurs in release builds.
      Instead, explicitly handle potential overflows using the standard library's checked,
      saturating, or wrapping operations.

``guideline`` Title
-------------------

The Title **MUST** provide a description of the guideline.

``guideline`` ``id``
--------------------

A unique identifier for each guideline. Guideline identifiers **MUST** begin with ``gui_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate-guideline-templates.py`` script to ensure
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

* ``provisional``
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

Content **SHOULD NOT** cover the rationale for the guideline, which is done in the ``rationale`` section.

Amplification
^^^^^^^^^^^^^

Guideline Content **MAY** contain a section titled *Amplification* followed by text that provides a more
precise description of the guideline title. An amplification is normative; if it conflicts with the
``guideline`` Title, the amplification **MUST** take precedence. This mechanism is convenient as it allows
a complicated concept to be conveyed using a short Title.

Exception
^^^^^^^^^

Guideline Content **MAY** contain a section titled *Exception* followed by text that that describes
situations in which the guideline does not apply. The use of exceptions permits the description of
some guidelines to be simplified. It is important to note that an exception is a situation in which
a guideline does not apply. Code that complies with a guideline by virtue of an exception does not
require a deviation.

``rationale``
=============

::

      .. rationale::
         :id: rat_kYiIiW8R2qD1
         :status: draft

         In debug builds, Rust performs runtime checks for integer overflow and will panic if detected.
         However, in release builds (with optimizations enabled), integer operations silently wrap
         around on overflow, creating potential for silent failures and security vulnerabilities.

         Safety-critical software requires consistent and predictable behavior across all build
         configurations. Explicit handling of potential overflow conditions improves code clarity,
         maintainability, and reduces the risk of numerical errors in production.

``rationale`` ``id``
--------------------

A unique identifier for each rationale. Rationale identifiers **MUST** begin with ``rat_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate-guideline-templates.py`` script to ensure
compliance.

``rationale`` ``status``
------------------------

The ``status`` option of a ``rationale`` **MUST** match the ``status`` of its parent ``guideline``.

Rationale Content
-----------------

TODO(pete.levasseur)

``non_compliant_example``
=========================

::

      .. non_compliant_example::
         :id: non_compl_ex_PO5TyFsRTlWv
         :status: draft

          .. code-block:: rust

            fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                // Potential for silent overflow in release builds
                current + velocity
            }

``non_compliant_example`` ``id``
--------------------------------

A unique identifier for each ``non_compliant_example``. ``non_compliant_example`` identifiers
**MUST** begin with ``non_compl_ex_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate-guideline-templates.py`` script to ensure
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

The Code Explanation of a `non_compliant_example` **MUST** explain in prose the reason the guideline
when not applied results in code which is undesirable.

The Code Explanation of a `non_compliant_example` **MAY** be a simple explanation no longer than
a sentence.

The Code Explanation of a ``non_compliant_example`` **SHOULD** be no longer than necessary to explain
the Code Example that follows.

``non_compliant_example`` Code Example
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``non_compliant_example`` Code Example **MUST** have a single ``.. code-block:: rust``
in which the example code is placed.

A ``non_compliant_example`` Code Example **SHOULD** be made as short and simple to understand
as possible.

A ``non_compliant_example`` Code Example **SHOULD** include clarifying comments if complex and/or
long.

The Code Example of a ``non_compliant_example`` **MUST NOT** contain a guideline violation other
than the current guideline.

``compliant_example``
=====================

::

      .. compliant_example::
         :id: compl_ex_WTe7GoPu5Ez0
         :status: draft

          .. code-block:: rust

            fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                // Explicitly handle potential overflow with checked addition
                current.checked_add(velocity).expect("Position calculation overflowed")
            }

``compliant_example`` ``id``
----------------------------

A unique identifier for each ``compliant_example``. ``compliant_example`` identifiers
**MUST** begin with ``compl_ex_``.

These identifiers are considered **stable** across releases and **MUST NOT** be removed.
See ``status`` below for more.

**MUST** be generated using the ``generate-guideline-templates.py`` script to ensure
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

A ``compliant_example`` Code Example **MUST** have a single ``.. code-block:: rust``
in which the example code is placed.

A ``compliant_example`` Code Example **SHOULD** be made as short and simple to understand
as possible.

A ``compliant_example`` Code Example **SHOULD** include clarifying comments if complex and/or
long.

A ``compliant_example`` Code Example **MUST** comply with every guideline.

A ``compliant_example`` Code Example **SHOULD** try to illustrate the guideline by
getting close to violating it, but staying within compliance.

