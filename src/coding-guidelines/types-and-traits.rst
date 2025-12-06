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
      However, in release builds (with optimizations enabled),
      unless the flag `overflow-checks`_ is turned on, integer operations silently wrap around on overflow,
      creating potential for silent failures and security vulnerabilities.
      Note that overflow-checks only brings the default panic behavior from debug into release builds,
      avoiding potential silent wrap arounds.
      Nonetheless, abrupt program termination is not suitable and, therefore, turning this flag on must
      not be used as a substitute of explicit handling.
      Furthermore, the behavior in release mode is under consideration by the The Rust Language Design Team and in the future overflow checking
      may be turned on by default in release builds (it is a `frequently requested change`_).

      .. `overflow-checks <https://github.com/rust-lang/rust/blob/master/src/doc/rustc/src/codegen-options/index.md#overflow-checks>`_
      .. `frequently requested change <https://lang-team.rust-lang.org/frequently-requested-changes.html#numeric-overflow-checking-should-be-on-by-default-even-in-release-mode>`_

      Safety-critical software requires consistent and predictable behavior across all build configurations.
      Explicit handling of potential overflow conditions improves code clarity,
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

.. guideline:: Do Not Depend on Function Pointer Identity Across Crates
    :id: gui_QbvIknd9qNF6 
    :category: required
    :status: draft
    :release: unclear-latest
    :fls: fls_1kg1mknf4yx7
    :decidability: decidable
    :scope: system
    :tags: surprising-behavior

    Do not rely on the equality or stable identity of function pointers originating from different crates or that may be inlined,
    duplicated, or instantiated differently across compilation units, codegen units, or optimization profiles.

    Avoid assumptions about low-level metadata (such as symbol addresses) unless explicitly guaranteed by the Ferrocene Language Specification (FLS).
    Function address identity is not guaranteed by Rust and must not be treated as stable.
    Rust’s ``fn`` type is a zero-sized function item promoted to a function pointer, whose address is determined by the compiler backend.
    When a function resides in a different crate, or when optimizations such as inlining,
    link-time optimization, or codegen-unit partitioning are enabled,
    the compiler may generate multiple distinct code instances for the same function or alter the address at which it is emitted.

    Consequently, the following operations are not reliable:

    - Comparing function pointers for equality (``fn1 == fn2``)
    - Assuming a unique function address
    - Using function pointers as identity keys (e.g., in maps, registries, matchers)
    - Matching behavior based on function address

    This rule applies even when the functions are semantically identical, exported as ``pub``, or defined once in source form.

    .. rationale:: 
        :id: rat_xcVE5Hfnbb2u 
        :status: draft

        Compiler optimizations may cause function pointers originating from different crates to lose stable identity.
        Observed behaviors include:

        - Cross-crate inlining producing multiple code instantiations
        - Codegen-unit separation causing function emission in multiple units
        - Incremental builds producing variant symbol addresses
        - Link-time optimization merging or splitting functions unpredictably

        This behavior has resulted in real-world issues,
        such as the bug reported in `rust-lang/rust#117047 <https://github.com/rust-lang/rust/issues/117047>`_,
        where function pointer comparisons unexpectedly failed due to cross-crate inlining.

        Violating this rule may cause:

        - Silent logic failures: callbacks not matching, dispatch tables misbehaving.
        - Inappropriate branching: identity-based dispatch selecting wrong handler.
        - Security issues: adversary-controlled conditions bypassing function-based authorization/dispatch logic.
        - Nondeterministic behavior: correctness depending on build flags or incremental state.
        - Test-only correctness: function pointer equality passing in debug builds but failing in release/link-time optimization builds.

        In short, dependence on function address stability introduces non-portable, build-profile-dependent behavior,
        which is incompatible with high-integrity Rust.

    .. non_compliant_example::
        :id: non_compl_ex_MkAkFxjRTijx 
        :status: draft

        Due to cross-crate inlining or codegen-unit partitioning,
        the address of ``handler_a`` in crate ``B`` may differ from its address in crate A,
	    causing comparisons to fail as shown in this noncompliant code example:

        .. code-block:: rust

            // crate A
            pub fn handler_a() {}
            pub fn handler_b() {}
            rust

            // crate B
            use crate_a::{handler_a, handler_b};

            fn dispatch(f: fn()) {
                if f == handler_a {
                    println!("Handled by A");
                } else if f == handler_b {
                    println!("Handled by B");
                }
            }

            dispatch(handler_a);

            //  Error:  This may fail unpredictably if handler_a is inlined or duplicated.

    .. compliant_example::
        :id: compl_ex_oiqSSclTXmIi 
        :status: draft

        Replace function pointer comparison with an explicit enum as shown in this compliant example:

        .. code-block:: rust

            // crate A
            pub enum HandlerId { A, B }

            pub fn handler(id: HandlerId) {
                match id {
                    HandlerId::A => handler_a(),
                    HandlerId::B => handler_b(),
                }
            }

            // crate B
            use crate_a::{handler, HandlerId};

            fn dispatch(id: HandlerId) {
                handler(id);
            }

            dispatch(HandlerId::A);  // OK: semantically stable identity

    .. non_compliant_example::	    
        :id: non_compl_ex_MkAkFxjRTijy 
        :status: draft

        Function pointer used as a key is not guaranteed to have stable identity, as shown in this noncompliant example:

        .. code-block:: rust

            // crate A
            pub fn op_mul(x: i32) -> i32 { x * 2 }

	    // crate B
            use crate_a::op_mul;
            use std::collections::HashMap;

            let mut registry: HashMap<fn(i32) -> i32, &'static str> = HashMap::new();
            registry.insert(op_mul, "double");

            let f = op_mul;

            // Error: Lookup may fail if `op_mul` has multiple emitted instances.
            assert_eq!(registry.get(&f), Some(&"double"));

    .. compliant_example::
        :id: compl_ex_oiqSSclTXmIj 
        :status: draft

        This compliant example uses a stable identity wrappers as identity keys.
	    The ``id`` is a stable, programmer-defined identity, immune to compiler optimizations.
        The function pointer is preserved for behavior (``func``) but never used as the identity key.

        .. code-block:: rust

            // crate A

            pub fn op_mul(x: i32) -> i32 { x * 2 }
            pub fn op_add(x: i32) -> i32 { x + 2 }

            // Stable identity wrapper for an operation.
            #[derive(Copy, Clone, PartialEq, Eq, Hash)]
            pub struct Operation {
                pub id: u32,
                pub func: fn(i32) -> i32,
            }

            // Export stable descriptors.
            pub const OP_MUL: Operation = Operation { id: 1, func: op_mul };
            pub const OP_ADD: Operation = Operation { id: 2, func: op_add };

	    // crate B

            use crate_a::{Operation, OP_MUL, OP_ADD};
            use std::collections::HashMap;

            fn main() {
              let mut registry: HashMap<u32, &'static str> = HashMap::new();

              // Insert using stable identity key (ID), not function pointer.
              registry.insert(OP_MUL.id, "double");
              registry.insert(OP_ADD.id, "increment");

              // Later: lookup using ID
              let op = OP_MUL;

              // lookup works reliably regardless of inlining, LTO, CGUs, cross-crate instantiation, etc.
              assert_eq!(registry.get(&op.id), Some(&"double"));

              println!("OP_MUL maps to: {}", registry[&op.id]);
            }
	    
    .. non_compliant_example::	    
        :id: non_compl_ex_MkAkFxjRTijz
        :status: draft

        This noncompliant example relies on function pointer identity for deduplication:

        .. code-block:: rust

            // crate B
            let mut handlers: Vec<fn()> = Vec::new();

            fn register(h: fn()) {
                if !handlers.contains(&h) {
                    handlers.push(h);
                }
            }

            register(handler); // Error: may be inserted twice under some builds

    .. compliant_example::
        :id: compl_ex_oiqSSclTXmIk
        :status: draft

        This compliant example keeps identity-sensitive logic inside a single crate:

        .. code-block:: rust

            // crate A (single crate boundary)
            #[inline(never)]
            pub fn important_handler() {}

            pub fn is_important(f: fn()) -> bool {
                // Safe because identity and comparison are confined to one crate,
                // and inlining is prohibited.
                f == important_handler
            }
	    

	    
