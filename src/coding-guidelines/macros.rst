.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Macros
======

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

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_Pw7YCh4Iv47Z
      :status: draft

      Explanation of code example

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Procedural macros should not be used
   :id: gui_66FSqzD55VRZ
   :category: advisory
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_wn1i6hzg2ff7
   :decidability: decidable
   :scope: crate
   :tags: readability, reduce-human-error

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

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_AEKEOYhBWPMl
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

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

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_ti7GWHCOhUvT
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Shall not write code that expands macros
   :id: gui_uuDOArzyO3Qw
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_wjldgtio5o75
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_dNgSvC0SZ3JJ
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_g9j8shyGM2Rh
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_cFPg6y7upNdl
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

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

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_GLP05s9c1g8N
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

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

      Explanation of code example.
   
      .. code-block:: rust
   
        #[tokio::main]  // non-compliant
        async fn main() {

        }

   .. compliant_example::
      :id: compl_ex_Mg8ePOgbGJeW
      :status: draft

      Explanation of code example.
   
      .. code-block:: rust
   
        fn example_function() {
            // Compliant implementation
        }
   
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

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_pO5gP1aj2v4F
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }