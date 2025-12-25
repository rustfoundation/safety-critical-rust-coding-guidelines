.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Shall not use Function-like Macros
   :id: gui_WJlWqgIxmE8P
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_utd3zqczix
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_C8RRidiVzhRj
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_TjRiRkmBY6wG
      :status: draft

      Explanation of code example.

      .. rust-example::

        #[allow(dead_code)]
        fn example_function() {
            // Non-compliant implementation
        }
        #
        # fn main() {}

   .. compliant_example::
      :id: compl_ex_AEKEOYhBWPMl
      :status: draft

      Explanation of code example.

      .. rust-example::

        #[allow(dead_code)]
        fn example_function() {
            // Compliant implementation
        }
        #
        # fn main() {}
