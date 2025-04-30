.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Macros
======

.. guideline:: Procedural macros should not be used
   :id: gui_66FSqzD55VRZ
   :category: advisory
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_wn1i6hzg2ff7
   :decidability: decidable
   :scope: crate
   :tags: readability

   Macros should be expressed using declarative syntax
   in preference to procedural syntax.

   .. rationale::
      :id: rat_AmCavSymv3Ev
      :status: draft

      Procedural macros are not restricted to pure transcription and can contain arbitrary Rust code.
      This means they can be harder to understand, and cannot be as easily proved to work as intended.
      Procedural macros can have arbitrary side effects, which can exhaust compiler resources or
      expose a vulnerability for users of adopted code.

   .. non_compliant_example::
      :id: non_compl_ex_pJhVZW6a1HP9
      :status: draft

      (example of a simple expansion using a proc-macro)

      .. code-block:: rust

        // TODO

   .. compliant_example::
      :id: compl_ex_4VFyucETB7C3
      :status: draft

      (example of the same simple expansion using a declarative macro)

      .. code-block:: rust

        // TODO
