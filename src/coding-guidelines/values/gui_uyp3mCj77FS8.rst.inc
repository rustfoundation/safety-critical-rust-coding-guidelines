.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not create values from uninitialized memory except for union fields
   :id: gui_uyp3mCj77FS8
   :category: mandatory
   :status: draft
   :release: <TODO>
   :fls: fls_6lg0oaaopc26
   :decidability: undecidable
   :scope: system
   :tags: undefined-behavior, unsafe

   A program shall not create a value of any type from uninitialized memory,
   except when accessing a field of a union type,
   where such reads are explicitly defined to be permitted even if the bytes of that field are uninitialized.
   It is prohibited to interpret uninitialized memory as a value of any Rust type such as a
   primitive, aggregate, reference, pointer, struct, enum, array, or tuple.

   **Exception:** You can access a field of a union even when the backing bytes of that field are uninitialized provided that:

   - The resulting value has an unspecified but well-defined bit pattern.
   - Interpreting that value must still comply with the requirements of the accessed type
     (e.g., no invalid enum discriminants, no invalid pointer values, etc.).

   For example, reading an uninitialized u32 field of a union is allowed;
   reading an uninitialized bool field is disallowed because not all bit patterns are valid.

   .. rationale::
      :id: rat_kjFRrhpS8Wu6
      :status: draft

      Rust's memory model treats all types except unions as having an invariant that all bytes must be initialized before a value may be constructed.
      Reading uninitialized memory:

      - creates undefined behavior for most types,
      - may violate niche or discriminant validity,
      - may create invalid pointer values, or
      - may produce values that violate type invariants.

      The sole exception is that unions work like C unions: any union field may be read, even if it was never written.
      The resulting bytes must, however, form a valid representation for the field's type,
      which is not guaranteed if the union contains arbitrary data.

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db1
      :status: draft

      This noncompliant example creates a value of type ``u32`` from uninitialized memory via 
      `assume_init <https://doc.rust-lang.org/stable/std/mem/union.MaybeUninit.html#method.assume_init>`_:

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         let x: u32 = unsafe { MaybeUninit::uninit().assume_init() }; // UB
         # }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShU
      :status: draft

      Types such as ``u8``, ``u16``, ``u32``, and ``i128`` allow all possible bit patterns.
      Provided the memory is initialized, there is no undefined behavior.

      .. rust-example::

         union U {
             n: u32,
             bytes: [u8; 4],
         }

         # fn main() {
         let u = U { bytes: [0xFF, 0xEE, 0xDD, 0xCC] };
         let n = unsafe { u.n };   // OK — all bit patterns valid for u32
         # }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShV
      :status: draft

      This compliant example calls the ``write`` function to fully initialize low-level memory.

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         let mut x = MaybeUninit::<u64>::uninit();
         x.write(42);
         let val = unsafe { x.assume_init() }; // OK — value was fully initialized
         # }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db2
      :status: draft

      Creating a reference from arbitrary or uninitialized bytes is always undefined behavior.
      References must be valid, aligned, properly dereferenceable, and non-null.
      Uninitialized memory cannot satisfy these invariants.

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         let r: &u32 = unsafe { MaybeUninit::uninit().assume_init() }; // UB — invalid reference
         # }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db4
      :status: draft

      Not all bit patterns are valid pointers for all operations (e.g., provenance rules).
      You cannot create a pointer from unspecified bytes.
      Even a raw pointer type (e.g., ``*const T``) has validity rules.

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         let p: *const u32 = unsafe { MaybeUninit::uninit().assume_init() }; // UB
         # }
   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db5
      :status: draft

      Array elements must individually be valid values.

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         let mut arr: [MaybeUninit<u8>; 4] = unsafe { MaybeUninit::uninit().assume_init() };
         let a = unsafe { std::mem::transmute::<_, [u8; 4]>(arr) }; // UB — not all elements initialized
         # }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShT
      :status: draft

      The following code reads a union field:

      .. rust-example::

         union U {
            x: u32,
            y: f32,
         }

         # fn main() {
         let u = U { x: 123 }; // write to one field
         let f = unsafe { u.y }; // reading the other field is allowed
         # }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db3
      :status: draft

      Even though unions allow reads of any field, not all bit patterns are valid for a ``bool``.
      Unions do not relax type validity requirements.
      Only the read itself is allowed;
      the resulting bytes must still be a valid bool.

      .. rust-example::

         union U {
             b: bool,
             x: u8,
         }

         # fn main() {
         let u = U { x: 255 };        // 255 is not a valid bool representation
         let b = unsafe { u.b };      // UB — invalid bool
         # }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShW
      :status: draft

      Accessing padding bytes is allowed if not interpreted as typed data:

      .. rust-example::

         #[repr(C)]
         struct S {
             a: u8,
             b: u32,
         }

         # fn main() {
         let mut buf = [0u8; std::mem::size_of::<S>()];
         buf[0] = 10;
         buf[1] = 20; // writing padding is fine

         let p = buf.as_ptr() as *const S;
         let s = unsafe { p.read_unaligned() }; // OK — all *fields* are initialized (padding doesn't matter)
         # }
