.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Example guideline with bibliography
   :id: gui_Bib7x9KmPq2nL
   :category: advisory
   :status: draft
   :release: 1.0.0-latest
   :fls: fls_69zyas59o8ff
   :decidability: decidable
   :scope: module
   :tags: safety, undefined-behavior

   This is an example guideline demonstrating the bibliography feature.
   
   As documented in :cite:`gui_Bib7x9KmPq2nL:RUST-REF-UNION`, union types in Rust have specific safety requirements.
   The CERT C Coding Standard :cite:`gui_Bib7x9KmPq2nL:CERT-C-INT34` provides guidance on avoiding undefined behavior
   in shift operations, which applies to Rust as well.

   .. rationale::
      :id: rat_Bib7x9KmPq2nL
      :status: draft

      This guideline demonstrates how to include bibliographic references in coding guidelines.
      References help users find authoritative sources for the recommendations made.

   .. non_compliant_example::
      :id: non_compl_ex_Bib7x9KmPq2nL
      :status: draft

      This example shows code that violates the guideline.

      .. rust-example::

         fn main() {
             // Non-compliant code example
             let x = 42;
             println!("{}", x);
         }

   .. compliant_example::
      :id: compl_ex_Bib7x9KmPq2nL
      :status: draft

      This example shows the correct way to follow the guideline.

      .. rust-example::

         fn main() {
             // Compliant code example
             let x: i32 = 42;
             println!("{}", x);
         }

   .. bibliography::
      :id: bib_Bib7x9KmPq2nL
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_Bib7x9KmPq2nL:RUST-REF-UNION`
           - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html
         * - :bibentry:`gui_Bib7x9KmPq2nL:CERT-C-INT34`
           - SEI CERT C Coding Standard. "INT34-C. Do not shift an expression by a negative number of bits." https://wiki.sei.cmu.edu/confluence/x/ItcxBQ
