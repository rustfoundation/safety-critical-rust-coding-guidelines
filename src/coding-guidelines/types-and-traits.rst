.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Types and Traits
================

.. guideline:: Avoid Implicit Integer Wrapping
   :id: gui_xztNdXA2oFNB
   :category: required
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_cokwseo3nnr
   :decidability: decidable
   :scope: module
   :tags: numerics

   Code must not rely on Rust's implicit integer wrapping behavior that may occur in release
   builds. Instead, explicitly handle potential overflows using the standard library's checked,
   saturating, or wrapping operations.

   .. rationale::
      :id: rat_kYiIiW8R2qD1
      :status: draft

      In debug builds, Rust performs runtime checks for integer overflow and will panic if detected.
      However, in release builds (with optimizations enabled), unless the flag `overflow-checks`_ is
      turned on, integer operations silently wrap around on overflow, creating potential for silent
      failures and security vulnerabilities. Note that overflow-checks only brings the default panic
      behavior from debug into release builds, avoiding potential silent wrap arounds. Nonetheless,
      abrupt program termination is usually not suitable and, therefore, turning this flag on must
      not be used as a substitute of explicit handling. Furthermore, the behavior in release mode is
      under consideration by the The Rust Language Design Team and in the future overflow checking
      may be turned on by default in release builds (it is a `frequently requested change`_).

      .. _overflow-checks: https://github.com/rust-lang/rust/blob/master/src/doc/rustc/src/codegen-options/index.md#overflow-checks
      .. _frequently requested change: https://lang-team.rust-lang.org/frequently-requested-changes.html#numeric-overflow-checking-should-be-on-by-default-even-in-release-mode

      Safety-critical software requires consistent and predictable behavior across all build
      configurations. Explicit handling of potential overflow conditions improves code clarity,
      maintainability, and reduces the risk of numerical errors in production.

   .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWv
      :status: draft

       .. code-block:: rust

         fn calculate_next_position(current: u32, velocity: u32) -> u32 {
             // Potential for silent overflow in release builds
             current + velocity
         }

   .. compliant_example::
      :id: compl_ex_WTe7GoPu5Ez0
      :status: draft

       .. code-block:: rust

         fn calculate_next_position(current: u32, velocity: u32) -> u32 {
             // Explicitly handle potential overflow with checked addition
             current.checked_add(velocity).expect("Position calculation overflowed")
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

    Do not access memory using a pointer with an incorrect provenance.
    Pointers, including values of reference type, have two components.
    The pointer’s address identifies the memory location where the pointer is currently pointing.
    The pointer’s provenance determines where and when the pointer is allowed to access memory.

    Whether a memory access with a given pointer causes undefined behavior (UB) depends on both the address and the provenance:
    the same address can access memory with one provenance but have undefined behavior with another provenance.

    Pointer comparisons are permitted only when both pointers are guaranteed to reference the same allocation.

    Code shall not rely on:

    - Layout of variables in memory
    - Assumed field layout of structs without ``repr(C)`` or ``repr(packed)``
    - Outcomes of pointer arithmetic across allocation boundaries

    This rule ignores any metadata that may come with wide pointers;
    it only pertains to thin pointers and the data part of a wide pointer.

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
