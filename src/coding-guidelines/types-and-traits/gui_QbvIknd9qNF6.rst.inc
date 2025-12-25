.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not depend on function pointer identity
   :id: gui_QbvIknd9qNF6
   :category: required
   :status: draft
   :release: unclear-latest
   :fls: fls_1kg1mknf4yx7
   :decidability: decidable
   :scope: system
   :tags: surprising-behavior

   Do not rely on the equality or stable identity of function pointers.

   **Exception**

   ``#[no_mangle]`` functions are guaranteed to have a single instance.

   .. rationale::
      :id: rat_kYiIiW8R2qD3
      :status: draft

      Functions may be instantiated multiple times.
      They may, for example, be instantiated every time they are referenced.
      Only ``#[no_mangle]`` functions are guaranteed to be instantiated a single time,
      but can cause undefined behavior if they share a symbol with other identifiers.

      Avoid assumptions about low-level metadata (such as symbol addresses) unless explicitly guaranteed by the Ferrocene Language Specification (FLS).
      Function address identity is not guaranteed and must not be treated as stable.
      Rust’s ``fn`` type is a zero-sized function item promoted to a function pointer, whose address is determined by the compiler backend.
      When a function resides in a different crate or codegen-unit partitioning is enabled,
      the compiler may generate multiple distinct code instances for the same function or alter the address at which it is emitted.

      Consequently, the following operations are unreliable for functions which are not ``#[no_mangle]``:

      - Comparing function pointers for equality (``fn1 == fn2``) 1Code has comments. Press enter to view.
      - Assuming a unique function address
      - Using function pointers as identity keys (e.g., in maps, registries, matchers) 1Code has comments. Press enter to view.
      - Matching behavior based on function address unless you instruct the linker to put a (#[no_mangle]) function at a specific address

      This rule applies even when the functions are semantically identical, exported as ``pub``, or defined once in source form.

      .. rationale::
         :id: rat_xcVE5Hfnbb2u
         :status: draft

         Compiler optimizations may cause function pointers to lose stable identity, for example:

         - Cross-crate inlining can produce multiple code instantiations
         - Codegen-unit separation can cause function emission in multiple codegen units
         - Function implementations may be merged as an optimization. 
           
         Functions that are equivalent based only on specific hardware semantics may be merged in the machine-specific backend.
         For example:

          .. rust-example::

         #[unsafe(no_mangle)]
         fn foo(x: *mut i32, y: *mut i32) {
             unsafe {
                 let a = &mut *x;
                 let b = &mut *y;
                 *a = *b;
             }
         }

         #[unsafe(no_mangle)]
         fn bar(x: *mut i32, y: *mut i32) {
             unsafe {
                 x.write(y.read());
             }
         }

         For specific backends, That is, the two functions are deduplicated, and therefore have the same address.
         This happened even though these two functions have different behavior in the abstract machine:
         the ``foo`` function has undefined behavior if ``x`` and ``y`` alias, while the ``bar`` function doesn't.

         This behavior has resulted in real-world issues,
         such as the bug reported in `rust-lang/rust#117047 <https://github.com/rust-lang/rust/issues/117047>`_,
         where function pointer comparisons unexpectedly failed because the function in question was instantiated multiple times.

         Violating this rule may cause:

         - Silent logic failures: callbacks not matching, dispatch tables misbehaving.
         - Inappropriate branching: identity-based dispatch selecting wrong handler.
         - Security issues: adversary-controlled conditions bypassing function-based authorization/dispatch logic.
         - Nondeterministic behavior: correctness depending on build flags or incremental state.
         - Test-only correctness: function pointer equality passing in debug builds but failing in release/link-time optimization builds.

         In short, dependence on function address stability introduces non-portable, build-profile-dependent behavior,
         which is incompatible with high-integrity Rust.

   .. non_compliant_example::
      :id: non_compl_ex_MkAkFxjRTijy
      :status: draft

      In this noncompliant example, the ``write_first`` and ``write_second`` functions each initialize one field within a ``MaybeUninit``,
      and write ``uninit`` to the other.
      If those addresses are equal, the code at that address must initialize both fields,
      as we could call the same code and then assume either field to be initialized.
      In that case it should be sound to call a function pointer created from that address and assume that both fields were initialized,
      even though you didn't write any such function.
      It's the only way the same function pointer could be a valid implementation of both functions.
      MyMaybeUninit - A union with two fields: uninit (empty) and init (a 4-byte tuple). The #[repr(align(4))] ensures 4-byte alignment.
      write_first and write_second - Two nearly identical functions that:

      * Initialize then "uninitialize" the union
      * Write to different subsets of init: write_first sets indices 0, 1, 3; write_second sets 0, 2, 3

      get_a - 

      Compares the addresses of the two functions
      If the compiler merged them (ICF), addr1 == addr2 is true
      It then calls the function through a transmuted pointer
      The comments claim that if merged, calling the single function should satisfy both functions' postconditions (setting both .1 and .2)

       .. rust-example::

         // recently started warning by default
         #![allow(function_casts_as_integer)]
         
         #[repr(align(4))]
         union MyMaybeUninit {
             uninit: (),
             // extra fields to make it more likely that both
             // functions are compiled to a single 4-byte write
             init: (u8, u8, u8, u8),
         }
         
         #[unsafe(no_mangle)]
         fn write_first(a: &mut MyMaybeUninit) {
             *a = MyMaybeUninit { init: (0, 1, 2, 3) };
             *a = MyMaybeUninit { uninit: () };
             a.init.0 = 0;
             a.init.1 = 1;
             a.init.3 = 3;
         }
         
         #[unsafe(no_mangle)]
         fn write_second(a: &mut MyMaybeUninit) {
             *a = MyMaybeUninit { init: (0, 1, 2, 3) };
             *a = MyMaybeUninit { uninit: () };
             a.init.0 = 0;
             a.init.2 = 2;
             a.init.3 = 3;
         }
         
         fn get_a() -> (u8, u8, u8, u8) {
             let mut a = MyMaybeUninit { init: (0, 0, 0, 0) };
             let addr1 = write_first as usize;
             let addr2 = write_second as usize;
             if addr1 == addr2 {
                 unsafe {
                     let ptr = addr1 as usize as *const ();
                     let f: fn(&mut MyMaybeUninit) = core::mem::transmute(ptr);
                     f(&mut a);
                 }
                 // Assuming that calling the (int as fnptr) is valid for either function,
                 // we can assume that
                 //  - `a.init.1 = 1` (because calling `write_first` ensures that)
                 //  - `a.init.2 = 2` (because calling `write_second` ensures that)
             }
             unsafe { a.init }
         }
         
         fn main() {
             println!("{:?}", get_a());
         }


   .. non_compliant_example::
      :id: non_compl_ex_MkAkFxjRTijx
      :status: draft

      Due to cross-crate inlining or codegen-unit partitioning,
      the address of ``handler_a`` in crate ``B`` may differ from its address in crate ``A``,
      causing comparisons to fail as shown in this noncompliant code example:

       .. rust-example::

         // crate A
         pub fn handler_a() {}
         pub fn handler_b() {}

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

         //  Error:  This may fail unpredictably if 'handler_a' is inlined or duplicated.

   .. compliant_example::
      :id: compl_ex_oiqSSclTXmIi
      :status: draft

      Replace function pointer comparison with an explicit enumeration type as shown in this compliant example:

       .. rust-example::

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

      A function pointer used as a key is not guaranteed to have stable identity, as shown in this noncompliant example:

       .. rust-example::

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

       .. rust-example::

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

       .. rust-example::

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

       .. rust-example::

         // crate A (single crate boundary)
         #[inline(never)]
         pub fn important_handler() {}

         pub fn is_important(f: fn()) -> bool {
             // Safe because identity and comparison are confined to one crate,
             // and inlining is prohibited.
             f == important_handler
         }
