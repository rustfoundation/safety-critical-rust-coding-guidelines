.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Shall ensure complete hygiene of macros
   :id: gui_8hs33nyp0ipX
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_xlfo7di0gsqz
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_e9iS187skbHH
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_lRt4LBen6Lkc
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
      :id: compl_ex_GLP05s9c1g8N
      :status: draft

      Explanation of code example.

      .. rust-example::

        #[allow(dead_code)]
        fn example_function() {
            // Compliant implementation
        }
        #
        # fn main() {}
