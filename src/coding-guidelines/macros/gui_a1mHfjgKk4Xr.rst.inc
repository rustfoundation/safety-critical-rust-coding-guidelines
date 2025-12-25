.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Shall not invoke macros
   :id: gui_a1mHfjgKk4Xr
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_vnvt40pa48n8
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_62mSorNF05kD
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_hP5KLhqQfDcd
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
      :id: compl_ex_ti7GWHCOhUvT
      :status: draft

      Explanation of code example.

      .. rust-example::

        #[allow(dead_code)]
        fn example_function() {
            // Compliant implementation
        }
        #
        # fn main() {}
