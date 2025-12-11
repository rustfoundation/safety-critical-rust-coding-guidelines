.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Types and Traits
================

.. guideline:: Use strong types to differentiate between logically distinct values
   :id: gui_xztNdXA2oFNC
   :category: advisory
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_cokwseo3nnr
   :decidability: undecidable
   :scope: module
   :tags: types, safety, understandability

   Parameters and variables with logically distinct types must be statically distinguishable by the type system.

   Use a newtype (e.g., ``struct Meters(u32);``) when:
   
   * Two or more quantities share the same underlying primitive representation but are logically distinct
   * Confusing them would constitute a semantic error
   * You need to improve type safety and encapsulation
   * You need to enable trait-based behavior
   * You need to establish new invariants
   
   .. rationale::
      :id: rat_kYiIiW8R2qD2
      :status: draft

      This rule ensures that parameters and variables convey intent directly through the type system to avoid accidental misuse of values with identical primitives but different semantics.
      In particular:

      * Prevents mixing logically distinct values.
        Primitive types like ``u32`` or ``u64`` can represent lengths, counters, timestamps, durations, IDs, or other values.
        Different semantic domains can be confused, leading to incorrect computations.
        The Rust type system prevents such mistakes when semantics are encoded into distinct types.
      * Improves static safety.
        Statically distinct types allow the compiler to enforce domain distinctions.
        Accidental swapping of parameters or returning the wrong quantity becomes a compile-time error.
      * Improves readability and discoverability.
        Intent-revealing names (``Meters``, ``Seconds``, ``UserId``) make code self-documenting.
        Type signatures become easier to read and understand.
      * Enables domain-specific trait implementations.
        Statically distinct types allow you to implement ``Add``, ``Mul``, or custom traits in ways that match the domain logic.
        Aliases cannot do this, because they are not distinct types.
      * Supports API evolution.
        Statically distinct types act as strong API contracts that can evolve independently from their underlying representations.

   .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWw
      :status: draft

      This noncompliant example uses primitive types directly, leading to potential confusion between ``distance`` and ``time``.
      Nothing prevents the caller from passing ``time`` as ``distance`` or vice-versa.
      The units of each type are not clear from the function signature alone.
      Mistakes compile cleanly and silently produce wrong results.

       .. code-block:: rust

         fn travel(distance: u32, time: u32) -> u32 {
            distance / time
         }

         fn main() {
            let d = 100;
            let t = = 10;
            let _result = travel(t, d);  // Compiles, but semantically incorrect
         }

   .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWv
      :status: draft

      This noncompliant example uses aliases instead of distinct types.
      Aliases do not create new types, so the compiler cannot enforce distinctions between ``Meters`` and ``Seconds``.
     
      Aliases cannot do this, because they are not distinct types.
      This noncompliant example uses primitive types directly, leading to potential confusion between ``distance`` and ``time``.
      Nothing prevents the caller from passing ``time`` as ``distance`` or vice-versa.
      The units of each type are not clear from the function signature alone.
      Mistakes compile cleanly and silently produce wrong results.

       .. code-block:: rust

         type Meters = u32;
         type Seconds = u32;
         type MetersPerSecond = u32;

         fn travel(distance: Meters, time: Seconds) -> MetersPerSecond {
            distance / time
         }

         fn main() {
            let d: Meters = 100;
            let t: Seconds = 10;
            let _result = travel(t, d);  // Compiles, but semantically incorrect
         }

   .. compliant_example::
      :id: compl_ex_WTe7GoPu5Ez1
      :status: draft

      This compliant example uses newtypes to create distinct types for ``Meters``, ``Seconds``, and ``MetersPerSecond``.
      The compiler enforces correct usage, preventing accidental swapping of parameters.
      The function signature clearly conveys the intended semantics of each parameter and return value.  

       .. code-block:: rust

         use std::ops::Div;

         #[derive(Debug, Clone, Copy)]
         struct Meters(u32);

         #[derive(Debug, Clone, Copy)]
         struct Seconds(u32);

         #[derive(Debug, Clone, Copy)]
         struct MetersPerSecond(u32);

         impl Div<Seconds> for Meters {
             type Output = MetersPerSecond;

             fn div(self, rhs: Seconds) -> Self::Output {
                  MetersPerSecond(self.0 / rhs.0)
             }
          }
          
          fn main() {
              let d = Meters(100);
              let t = Seconds(10);
              let result = d / t;  // Clean and type-safe!
              println!("{:?}", result);  // MetersPerSecond(10)
          }

.. guideline:: Do not access memory using a pointer with an incorrect provenance
    :id: gui_5iE7d65xGPpJ 
    :category: required
    :status: draft
    :release: unclear-latest
    :fls: fls_bw8zutjcteki
    :decidability: decidable
    :scope: system
    :tags: surprising-behavior

    Do not access memory using a pointer with an incorrect `provenance <https://doc.rust-lang.org/std/ptr/index.html#provenance>`__.
    Pointers, including values of reference type, have two components.
    The pointer’s address identifies the memory location where the pointer is currently pointing.
    The pointer’s provenance determines where and when the pointer is allowed to access memory and if it is allowed to mutate the memory.

    Whether a memory access with a given pointer causes undefined behavior (UB) depends on both the address and the provenance;
    the same address can access memory with one provenance but have undefined behavior with another provenance.

    Pointer comparisons are permitted only when both pointers are guaranteed to reference the same allocation.

    Code shall not rely on:

    - Layout of variables in memory
    - Assumed field layout of structs without ``repr(C)`` or ``repr(packed)``
    - Outcomes of pointer arithmetic across allocation boundaries

    This rule ignores any `metadata <https://doc.rust-lang.org/std/ptr/trait.Pointee.html#pointer-metadata>`__ that may come with wide pointers;
    it only pertains to thin pointers and the address part of a wide pointer.

    .. rationale:: 
        :id: rat_AFpgNhAMQ4eC 
        :status: draft

        Although raw pointer comparison is not itself undefined behavior;
        comparing pointers with different provenance can give surprising results which might cause logic errors,
        portability issues, and inconsistent behavior across different optimization levels, builds, or platforms.
        Specifically, the result of comparing pointers with different providence is guaranteed to be the comparison of the pointer addresses.
        However, the addresses that are selected for allocations is unspecified.

        Pointer equality or ordering is only meaningful when both pointers are derived from the same allocated object or block of memory.
        Comparisons across unrelated allocations are semantically meaningless and must be avoided.

    .. non_compliant_example::
        :id: non_compl_ex_c5NpFUId5lMp 
        :status: draft

        This noncompliant example creates a mutable raw pointer and a shared reference to ``x``,
        and derives a raw pointer from that shared reference.
        The shared reference ``shrref`` is converted to a raw constant pointer, and then to a raw mutable pointer.

        This produces another raw pointer ``shrptr`` to the same memory location ``x``, but its provenance is different:
        - ``ptr`` is derived from from ``&mut x``
        - ``shrptr`` is derived from a shared reference ``&x``
        
        As a result, this noncompliant example has undefined behavior when writing ``x`` through the shared reference ``shrptr``
        attempting a write access using using a tag that only grants ``SharedReadOnly`` permission for this location.

        .. code-block:: rust

           fn main() {
               unsafe {
                   let mut x = 5;
                   // Setup a mutable raw pointer and a shared reference to `x`,
                   // and derive a raw pointer from that shared reference.
                   let ptr = &mut x as *mut i32;
                   let shrref = &*ptr;
                   let shrptr = shrref as *const i32 as *mut i32;
                   // `ptr` and `shrptr` point to the same address.
                   assert_eq!(ptr, shrptr);
                   // Writing `x` through `shrptr` is undefined behavior
                   shrptr.write(0); 
                   println!("x = {}", x);
               }
           }

    .. compliant_example::
        :id: compl_ex_pBPeA9tBOnxk
        :status: draft

        This compliant example eliminates the undefined behavior by writing to ``x`` through ``ptr`` which is derived directly from ``&mut x``.

        .. code-block:: rust

           fn main() {
               unsafe {
                   let mut x = 5;
                   // Setup a mutable raw pointer and a shared reference to `x`,
                   // and derive a raw pointer from that shared reference.
                   let ptr = &mut x as *mut i32;
                   let shrref = &*ptr;
                   let shrptr = shrref as *const i32 as *mut i32;
                   // `ptr` and `shrptr` point to the same address.
                   assert_eq!(ptr, shrptr);
                   // Eliminate UB by writing through `ptr`
                   ptr.write(0); 
                   println!("x = {}", x);
               }
           }

    .. non_compliant_example::
        :id: non_compl_ex_c5NpFUId5lMo 
        :status: draft

        This noncompliant example allocates two local ``u32`` variables on the stack.
        The order of these two variables in memory is unspecified behavior. 
        The code then creates a raw pointer to ``v2`` and a raw pointer to ``v1``.
        Adds the address stored in ``v1`` to 1 × ``size_of::<u32>()`` = 4 bytes using 
        `wrapping_offset <https://doc.rust-lang.org/std/primitive.pointer.html#method.wrapping_offset>`__ which:

        - ignores provenance
        - may produce an arbitrary, invalid, or meaningless pointer
        - is always allowed but does not guarantee the pointer points to anything valid

        Comparing two `values <https://rust-lang.github.io/fls/glossary.html#term_value>`__ of `raw pointer types 
        <https://rust-lang.github.io/fls/glossary.html#term_raw_pointer_type>`__ compares the addresses of the 
        `values <https://rust-lang.github.io/fls/glossary.html#term_value>`__.

        This code then compares ptr (a pointer to ``v2``) with ``ptr2`` (a pointer to ``v1`` + 4 bytes).
        Because the stack layout is unspecified behavior,
        the result of this comparison depends on how the compiler the memory layout for ``v1`` and ``v2`` on the stack.
        The result may change across:

        - compiler versions
        - optimization levels
        - targets
        - small code changes
        - builds with or without link-time optimization

        This noncompliant example does not contain undefined behavior (because no pointer is dereferenced) but it does depend on unspecified behavior, 
        meaning that the program is valid, but the results are undefined.

        .. code-block:: rust

            pub fn raw_ptr_comparison(){
                let v1: u32 = 1;
                let v2: u32 = 2;
                let ptr = &v2 as *const u32;
                let ptr2 = (&v1 as *const u32).wrapping_offset(1);
                if ptr == ptr2 {
                    println!("Same");
                }
                else{
                    println!("Not the same");
                }
            }

    .. compliant_example::
        :id: compl_ex_pBPeA9tBOnxj 
        :status: draft

        This compliant example creates a mutable array of 16 bytes on the stack where all bytes are zero-initialized.
        The entire array is one contiguous allocation.
        The code creates a raw pointer ``p`` of type ``*const u8`` to the first element of the array (that is, ``buf[0]``).
        The ptr ``p`` points at the start of the allocation.
        The code then uses pointer arithmetic to compute a pointer ``q`` which points 4 elements past ``p``.
        Because the element type is ``u8``, this means “4 bytes past ``p``\ ”.
        The pointer arithmetic is safe as long as the resulting pointer stays within the same allocation (it does).
        This is permitted because pointer arithmetic is allowed within the same allocated object.

        Finally, the code compares the numerical address values of ``p`` and ``q``.
        Pointer comparison is always allowed.
        Comparing pointers from the same allocation is meaningful and defined.
        Because ``p`` points to the beginning and ``q`` to a later part of the same array, ``same_block`` becomes ``true``.

        .. code-block:: rust

            let mut buf = [0u8; 16];
            let p = buf.as_ptr();
            let q = unsafe { p.add(4) };

            let same_block = p < q; // ok: comparison within same allocation
