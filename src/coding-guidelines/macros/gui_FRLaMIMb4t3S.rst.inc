.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not hide unsafe blocks within macro expansions
   :id: gui_FRLaMIMb4t3S
   :category: required
   :status: draft
   :release: todo
   :fls: fls_4vjbkm4ceymk
   :decidability: todo
   :scope: todo
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_WJubG7KuUDLW
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_AyFnP0lJLHxi
      :status: draft

      Explanation of code example.

      .. rust-example::

        fn example_function() {
            // Non-compliant implementation
        }
        #
        # fn main() {}

   .. compliant_example::
      :id: compl_ex_pO5gP1aj2v4F
      :status: draft

      Explanation of code example.

      .. rust-example::

        fn example_function() {
            // Compliant implementation
        }
        #
        # fn main() {}
