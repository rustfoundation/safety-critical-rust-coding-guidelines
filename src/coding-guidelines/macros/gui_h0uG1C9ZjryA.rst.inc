.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Shall not use Declarative Macros
   :id: gui_h0uG1C9ZjryA
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_xa7lp0zg1ol2
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_U3AEUPyaUhcb
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_Gb4zimei8cNI
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
      :id: compl_ex_Pw7YCh4Iv47Z
      :status: draft

      Explanation of code example

      .. rust-example::

        #[allow(dead_code)]
        fn example_function() {
            // Compliant implementation
        }
        #
        # fn main() {}
