.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Values
======

.. guideline:: Do not create values from uninitialized memory except for union fields
   :id: gui_uyp3mCj77FS8
   :category: mandatory
   :status: draft
   :release: <TODO>
   :fls: fls_6lg0oaaopc26
   :decidability: undecidable
   :scope: system
   :tags: undefined-behavior

   A program shall not create a value of any type from uninitialized memory, except when accessing a field of a union type, where such reads are explicitly defined to be permitted even if the bytes of that field are uninitialized.
   It is prohibited to interpret uninitialized memory as a value of any Rust type (primitive, aggregate, reference, pointer, struct, enum, array, tuple, etc.)
   
   **Exception:** You can access a field of a union even when the backing bytes of that field are uninitialized provided that:

   - The resulting value has an unspecified but well-defined bit pattern.
   - Interpreting that value must still comply with the requirements of the accessed type (e.g., no invalid enum discriminants, no invalid pointer values, etc.).

   For example, reading an uninitialized u32 field of a union is allowed; reading an uninitialized bool field is disallowed because not all bit patterns are valid.

   .. rationale::
      :id: rat_kjFRrhpS8Wu6
      :status: draft

      Rust’s memory model treats all types except unions as having an invariant that all bytes must be initialized before a value may be constructed. Reading uninitialized memory:

      - creates undefined behavior for most types,
      - may violate niche or discriminant validity,
      - may create invalid pointer values,
      - or may produce values that violate type invariants.
      
      The sole exception is that unions work like C unions: any union field may be read, even if it was never written. The resulting bytes must, however, form a valid representation for the field’s type, which is not guaranteed if the union contains arbitrary data.

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db1
      :status: draft

      The following code creates a value from uninitialized memory via assume_init:

      .. code-block:: rust

         use std::mem::MaybeUninit;

         let x: u32 = unsafe { MaybeUninit::uninit().assume_init() }; // UB

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShT
      :status: draft

      The following code reads a union field:

      .. code-block:: rust

         union U {
            x: u32,
            y: f32,
         }

         let u = U { x: 123 }; // write to one field
         let f = unsafe { u.y }; // reading the other field is allowed
