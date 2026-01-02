.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not read uninitialized memory of any non-union type as a typed value
   :id: gui_uyp3mCj77FS8
   :category: mandatory
   :status: draft
   :release: <TODO>
   :fls: fls_6lg0oaaopc26
   :decidability: undecidable
   :scope: system
   :tags: undefined-behavior, unsafe

   Do not read uninitialized memory of any non-union type as a typed value :cite:`gui_xK9pLm2nQR4t:RUSTNOMICON-UNINIT`.
   This is sometimes referred to as *transmuting* or *read-at-type*. 
   Memory can remain uninitialized if it is not read as a type.
   
   Reading from a union is covered by `Do not read from union fields that may contain uninitialized bytes
   <https://coding-guidelines.arewesafetycriticalyet.org/coding-guidelines/types-and-traits/index.html#gui_UnionPartialInit>`_.

   Calling `assume_init <https://doc.rust-lang.org/stable/std/mem/union.MaybeUninit.html#method.assume_init>`_
   :cite:`gui_aE3fNc6dWX1v:MAYBEUNINIT-DOC` or any of the following related functions is treated in the same manner as a typed read:

   * ``assume_init_drop``
   * ``assume_init_mut``
   * ``assume_init_read``
   * ``assume_init_ref``
   * ``array_assume_init``

   Calling any of these function on memory that is not yet fully initialized is undefined behavior :cite:`gui_vB7sHj5wYZ8u:RUST-REF-BEHAVIOR`.
   The memory must be properly initialized according to the requirements of the variable's type :cite:`gui_uZ0zDq8rST1b:UCG-VALIDITY`.
   For example, a variable of reference type must be aligned, non-null, and point to valid memory.
   Similarly, entirely uninitialized memory may have any content, while a ``bool`` must always be ``true`` or ``false``.
   Consequently, reading an uninitialized ``bool`` is undefined behavior.
 
   .. rationale::
      :id: rat_kjFRrhpS8Wu6
      :status: draft

      Rust's memory model requires that all bytes must be initialized before being read as a typed value
      :cite:`gui_xK9pLm2nQR4t:RUSTNOMICON-UNINIT` :cite:`gui_kP8qTg4hUS2w:FERROCENE-SPEC`.
      Reading uninitialized memory as a typed value is undefined behavior :cite:`gui_vB7sHj5wYZ8u:RUST-REF-BEHAVIOR`.
      This guideline aligns with functional safety standards :cite:`gui_oT4tXk2lMN5y:ISO-26262`
      :cite:`gui_qV6vZm4nOP7z:IEC-61508` and secure coding practices.

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db1
      :status: draft

      This noncompliant example extracts a value of type ``u32`` from uninitialized memory within a ``MaybeUninit<T>`` container,
      which is undefined behavior.

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             // Reading uninitialized memory as a typed value is undefined behavior
             let x: u32 = unsafe { MaybeUninit::uninit().assume_init() }; // noncompliant
         }

   .. compliant_example::
      :id: compl_ex_Ke869nSXuShV
      :status: draft

      This compliant example creates an uninitialized variable ``x`` of type ``MaybeUninit<u64>``.
      The code calls the ``write`` function to write the value 42 to ``x``.
      The call to ``assume_init`` asserts that the value is initialized and extracts the value of type ``u64``.
      This call is compliant with this rule because the memory has been properly initialized by the call to ``write(42)``.
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
      :id: non_compl_ex_Qb5GqYTP6db4
      :status: draft

      This noncompliant example creates a pointer from uninitialized memory.
      Not all bit patterns are valid pointers for all operations (e.g., provenance rules) :cite:`gui_uZ0zDq8rST1b:UCG-VALIDITY`.
      You cannot create a pointer from unspecified bytes.
      Even a raw pointer type (e.g., ``*const T``) has validity rules `gui_vB7sHj5wYZ8u:RUST-REF-BEHAVIOR`.

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             let p: *const u32 = unsafe { MaybeUninit::uninit().assume_init() }; // noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db2
      :status: draft

      This noncompliant example creates a reference from uninitialized memory.
      Creating a reference from arbitrary or uninitialized bytes is undefined behavior :cite:`gui_vB7sHj5wYZ8u:RUST-REF-BEHAVIOR`.
      References must be valid, aligned, dereferenceable, and non-null :cite:`gui_uZ0zDq8rST1b:UCG-VALIDITY`.
      Uninitialized memory cannot satisfy these requirements.

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             // Reading an invalid reference is undefined behavior
             let r: &u32 = unsafe { MaybeUninit::uninit().assume_init() }; // noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db3
      :status: draft

      This noncompliant example creates a reference from uninitialized memory.

      .. rust-example::

         use std::mem::MaybeUninit;
         use std::ptr;

         fn create_ref() {
             let mut uninit: MaybeUninit<&u8> = MaybeUninit::uninit();
             unsafe {
                 // write non-null and aligned address.
                 (&raw mut uninit).cast::<*const u8>().write(ptr::dangling());
                 // Undefined behavior occurs when asserting 'uninit' is a valid reference.
                 let _init = uninit.assume_init(); // noncompliant
             }
         }

         fn main() {
             create_ref();
         }

      The ``create_ref`` function has undefined behavior when creating a reference from a dangling pointer.
      It creates uninitialized memory sized for a reference (``&u8``).
      ``&raw mut uninit`` retrieves a raw mutable pointer to the ``MaybeUninit``.
      The ``.cast::<*const u8>()`` reinterprets it as a pointer to a raw pointer.
      The call to ``.write(ptr::dangling())`` writes a dangling pointer value.
      This creates a non-null, aligned pointer that does not point to a valid, initialized value.
      The call to ``assume_init`` asserts the ``MaybeUninit<&u8>`` is a valid ``&u8`` reference
      A reference (``&T``) has stricter requirements than a raw pointer.
      Even though the bit pattern looks like a valid pointer,
      the semantic requirements for a reference are violated.
      The compiler is allowed to assume references always point to valid data,
      so this can cause miscompilation.

   .. non_compliant_example::
      :id: non_compl_ex_Qb5GqYTP6db5
      :status: draft

      Array elements must individually be valid values.
      This noncompliant example creates an uninitialized array of four ``u8`` values.
      The call to ``.assume_init`` asserting that the array is initialized is valid here because 
      an array of ``MaybeUninit<u8>`` can contain uninitialized bytes.
      The call to ``std::mem::transmute`` reinterprets the ``[MaybeUninit<u8>; 4]`` as ``[u8; 4]``.
      This is undefined behavior, because the bytes were never initialized. 
      Even though all bit patterns (0-255) are valid for the ``u8`` type, the values must be initialized. 

      ``MaybeUninit<u8>`` can hold uninitialized memory — that's its purpose.
      ``u8`` cannot hold uninitialized memory — all 8 bits must be defined.
      The ``transmute`` performs a typed read that asserts the bytes are valid ``u8`` values.
      Reading uninitialized bytes as a concrete type is always undefined behavior.

      .. rust-example::

         use std::mem::MaybeUninit;

         fn main() {
             let mut arr: [MaybeUninit<u8>; 4] = unsafe { MaybeUninit::uninit().assume_init() };
             // Undefined behavior constructing an array of 'u8' from uninitialized memory. 
             let a = unsafe { std::mem::transmute::<_, [u8; 4]>(arr) }; // noncompliant
         }

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

   .. bibliography::
      :id: bib_WNCi5njUWLuY
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_wB2bFs0tUV3c:DO-178C`
           - RTCA, Inc. "DO-178C: Software Considerations in Airborne Systems and Equipment Certification." https://store.accuristech.com/standards/rtca-do-178c?product_id=2200105.

         * - :bibentry:`gui_xK9pLm2nQR4t:RUSTNOMICON-UNINIT`
           - The Rust Project Developers. "The Rustonomicon - Uninitialized Memory." https://doc.rust-lang.org/nomicon/uninitialized.html.

         * - :bibentry:`gui_vB7sHj5wYZ8u:RUST-REF-BEHAVIOR`
           - The Rust Project Developers. "The Rust Reference - Behavior considered undefined." https://doc.rust-lang.org/reference/behavior-considered-undefined.html.

         * - :bibentry:`gui_aE3fNc6dWX1v:MAYBEUNINIT-DOC`
           - The Rust Project Developers. "std::mem::MaybeUninit - Rust Standard Library Documentation." https://doc.rust-lang.org/stable/std/mem/union.MaybeUninit.html.

         * - :bibentry:`gui_kP8qTg4hUS2w:FERROCENE-SPEC`
           - Ferrocene GmbH. "Ferrocene Language Specification." https://spec.ferrocene.dev/.

         * - :bibentry:`gui_mR1rVi9jKL3x:MISRA-RUST`
           - MISRA Consortium Limited. "MISRA Rust Guidelines (Draft)." https://misra.org.uk/.

         * - :bibentry:`gui_oT4tXk2lMN5y:ISO-26262`
           - International Organization for Standardization. "ISO 26262 - Road vehicles - Functional safety." https://www.iso.org/standard/68383.html.

         * - :bibentry:`gui_qV6vZm4nOP7z:IEC-61508`
           - International Electrotechnical Commission. "IEC 61508 - Functional Safety of Electrical/Electronic/Programmable Electronic Safety-related Systems." https://www.iec.ch/functional-safety.

         * - :bibentry:`gui_sX8xBo6pQR9a:RUST-SAFETY-CRITICAL-WG`
           - Rust Foundation. "Rust Safety-Critical Consortium." https://github.com/rust-lang/safety-critical-consortium.

         * - :bibentry:`gui_uZ0zDq8rST1b:UCG-VALIDITY`
           - The Rust Project Developers. "Unsafe Code Guidelines - Validity Invariants." https://rust-lang.github.io/unsafe-code-guidelines/glossary.html#validity-and-safety-invariant.


     * - .. [CERT_RUST]
       - | Carnegie Mellon University Software Engineering Institute
         | "SEI CERT Rust Coding Standard"
         | https://wiki.sei.cmu.edu/confluence/display/rust
