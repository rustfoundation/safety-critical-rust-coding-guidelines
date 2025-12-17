.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not create values from uninitialized memory
   :id: gui_uyp3mCj77FS8
   :category: mandatory
   :status: draft
   :release: <TODO>
   :fls: fls_6lg0oaaopc26
   :decidability: undecidable
   :scope: system
   :tags: undefined-behavior, unsafe

   A program shall not create a value of any non-union type from uninitialized memory.
   Reading from a union is covered by a separate rule, `Do not read from union fields that may contain uninitialized bytes
   <https://coding-guidelines.arewesafetycriticalyet.org/coding-guidelines/types-and-traits/index.html#gui_UnionPartialInit>`_.
   It is prohibited to interpret uninitialized memory as a value of any type.
 
   .. rationale::
      :id: rat_kjFRrhpS8Wu6
      :status: draft

      Rust's memory model treats all types except unions as having an invariant that all bytes must be initialized before a value may be constructed.
      Reading uninitialized memory:

      - creates undefined behavior for most types,
      - may violate niche or discriminant validity,
      - may create invalid pointer values, or
      - may produce values that violate type invariants.
      
   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db1
      :status: draft

      This noncompliant example attempts to create a value of type ``u32`` from uninitialized memory by calling  
      `assume_init <https://doc.rust-lang.org/stable/std/mem/union.MaybeUninit.html#method.assume_init>`_:

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             // Reading uninitialized memory as a typed value is undefined behavior
             let x: u32 = unsafe { MaybeUninit::uninit().assume_init() }; // noncompliant
         }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShV
      :status: draft

      This compliant example creates an uninitialized allocation of type ``MaybeUninit<u64>``.
      The code calls the ``write`` function to write the value 42 into the ``MaybeUninit``.
      The call to ``assume_init`` asserts that the value is initialized and extracts the value of type ``u64``.
      This is valid because the memory has been initialized by the call to ``write(42)``.
      This is the canonical safe pattern for using ``MaybeUninit``.

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             let mut x = MaybeUninit::<u64>::uninit();
             x.write(42);
             // x is fully initialized
             let val = unsafe { x.assume_init() }; // compliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db2
      :status: draft

      This noncompliant example creates a reference from uninitialized memory.
      Creating a reference from arbitrary or uninitialized bytes is undefined behavior.
      References must be valid, aligned, properly dereferenceable, and non-null.
      Uninitialized memory cannot satisfy these invariants.

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         // Reading an invalid reference is undefined behavior
         let r: &u32 = unsafe { MaybeUninit::uninit().assume_init() }; // noncompliant
         # }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db4
      :status: draft

      This noncompliant example creates a pointer from uninitialized memory.
      Not all bit patterns are valid pointers for all operations (e.g., provenance rules).
      You cannot create a pointer from unspecified bytes.
      Even a raw pointer type (e.g., ``*const T``) has validity rules.

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             let p: *const u32 = unsafe { MaybeUninit::uninit().assume_init() }; // noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db5
      :status: draft

      Array elements must individually be valid values.
      This noncompliant example creates an uninitialized array of four ``u8`` values.
      The call to ``.assume_init`` asserting that the array is initialized is valid here because 
      an array of ``MaybeUninit<u8>`` can contain uninitialized bytes.
      The call to ``std::mem::transmute`` reinterprets the ``[MaybeUninit<u8>; 4]`` as ``[u8; 4]``.
      This is undefined behavior, because the bytes were never initialized. 
      Even though all bit patterns (0-255) are valid for the ``u8`` type, the values must be initalized. 

      ``MaybeUninit<u8>`` can hold uninitialized memory — that's its purpose.
      ``u8`` cannot hold uninitialized memory — all 8 bits must be defined.
      The ``transmute`` performs a typed read that asserts the bytes are valid ``u8`` values.
      Reading uninitialized bytes as a concrete type is always undefined behavior.

      .. rust-example::

         use std::mem::MaybeUninit;

         # fn main() {
         let mut arr: [MaybeUninit<u8>; 4] = unsafe { MaybeUninit::uninit().assume_init() };
         // Undefined behavior constructing an array of 'u8' from uninitialized memory. 
         let a = unsafe { std::mem::transmute::<_, [u8; 4]>(arr) }; // noncompliant
         # }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShW
      :status: draft

      This compliant example defines a C-layout ``struct`` with:

      * ``a``: 1 byte at offset 0
      * 3 bytes of padding (to align ``b`` to 4 bytes)
      * ``b``: 4 bytes at offset 4
      * Total size: 8 bytes

      The variable ``buf`` is a fully, zero-initialized 8-byte buffer.

      The first wo bytes of ``buf`` are overwritten.
      The byte buffer ``buf`` pointer is cast to a pointer to ``S``.
      The call to ``read_unaligned`` reads the ``struct`` without requiring alignment.

      This example is compliant because:

      * All bytes are initialized (buffer was zero-initialized)
      * All fields have valid values (``u8`` and ``u32`` accept any bit pattern)
      * Padding bytes don't need to be any specific value
      * ``read_unaligned`` handles the alignment issue

      .. rust-example::

         #[repr(C)]
         #[derive(Debug)]
         struct S {
             a: u8,
             b: u32,
         }

         fn main() {
             let mut buf = [0u8; std::mem::size_of::<S>()];
             buf[0] = 10;
             buf[1] = 20; // writing padding is fine

             let p = buf.as_ptr() as *const S;
             // All fields are initialized (padding doesn't matter)
             let s = unsafe { p.read_unaligned() }; // compliant
             println!("{:?}", s);
         }
