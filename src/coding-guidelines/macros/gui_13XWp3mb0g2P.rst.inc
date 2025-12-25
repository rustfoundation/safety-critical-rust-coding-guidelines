.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Attribute macros shall not be used
   :id: gui_13XWp3mb0g2P
   :category: required
   :status: draft
   :release: todo
   :fls: fls_4vjbkm4ceymk
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Attribute macros shall neither be declared nor invoked.
   Prefer less powerful macros that only extend source code.

   .. rationale::
      :id: rat_X8uCF5yx7Mpo
      :status: draft

      Attribute macros are able to rewrite items entirely or in other unexpected ways which can cause confusion and introduce errors.

   .. non_compliant_example::
      :id: non_compl_ex_eW374waRPbeL
      :status: draft

      The ``#[test]`` attribute macro transforms the function into a test harness entry point.

      .. rust-example::
          :no_run:

          #[test]  // non-compliant: attribute macro rewrites the item
          fn example_test() {
              assert!(true);
          }
          #
          # fn main() {}

   .. compliant_example::
      :id: compl_ex_Mg8ePOgbGJeW
      :status: draft

      Explanation of code example.

      .. rust-example::

        #[allow(dead_code)]
        fn example_function() {
            // Compliant implementation
        }
        #
        # fn main() {}
