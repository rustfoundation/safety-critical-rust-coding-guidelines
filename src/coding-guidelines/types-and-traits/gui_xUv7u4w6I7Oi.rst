.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Do not depend on function pointer identity
==========================================

.. guideline:: Do not depend on function pointer identity
   :id: gui_xUv7u4w6I7Oi
   :category: required
   :status: draft
   :release: unclear-latest
   :fls: fls_1kg1mknf4yx7
   :decidability: decidable
   :scope: system
   :tags: surprising-behavior

   Do not directly or indirectly compare function pointers or use them as identity keys.

   Indirect comparisons include:

   * Collection membership (``Vec::contains``, ``HashSet::contains``, ``HashSet::insert``, ``BTreeSet::contains``)
   * Map keys (``HashMap`` or ``BTreeMap`` keys based on function pointers)
   * Ordering comparisons (``<``, ``>``, ``<=``, ``>=``)
   * Sorting and binary search (``sort``, ``binary_search``)
   * Deduplication (``dedup``)
   * Iterator predicates (``find``, ``position``, ``any``, ``filter``) that compare pointers
   * Pattern matching guards that compare function pointers
   * Casting to ``usize`` and comparing addresses
   * Assertion macros (``assert_eq!``, ``debug_assert_ne!``)
   * ``matches!`` guards that compare function pointers

   **Exceptions**
   Functions marked ``#[no_mangle]`` are guaranteed to have a single instance, but relying on
   their addresses should still be limited to explicitly documented, linker-controlled layouts
   :cite:`gui_xUv7u4w6I7Oi:RUST-REF-NO-MANGLE`.

   .. rationale::
      :id: rat_jA36zzcpRKqW
      :status: draft

      Functions may be instantiated multiple times, and function pointer identity is not stable.
      Avoid assumptions about symbol addresses unless explicitly guaranteed by the Ferrocene
      Language Specification :cite:`gui_xUv7u4w6I7Oi:FLS`.
      Rust's ``fn`` type is a function item coerced to a function pointer whose address is
      determined by the compiler backend :cite:`gui_xUv7u4w6I7Oi:RUST-REF-FN-PTR`.
      Cross-crate inlining, codegen-unit partitioning, and link-time optimization can produce
      multiple instances or merge functions with identical machine code
      :cite:`gui_xUv7u4w6I7Oi:LLVM-LTO`.

      This behavior has resulted in real-world issues, such as the bug reported in
      :cite:`gui_xUv7u4w6I7Oi:RUST-ISSUE-117047`.

      Consequently, the following operations are unreliable for functions that are not
      ``#[no_mangle]``:

      * Comparing function pointers for equality or ordering
      * Assuming a unique function address
      * Using function pointers as identity keys (maps, registries, matchers)
      * Selecting behavior based on function addresses without linker guarantees

      Violating this rule may cause:

      * Silent logic failures (callbacks not matching, dispatch tables misbehaving)
      * Inappropriate branching (identity-based dispatch selecting the wrong handler)
      * Security issues (adversary-controlled conditions bypassing authorization logic)
      * Nondeterministic behavior (correctness depends on build flags or incremental state)

   .. non_compliant_example::
      :id: non_compl_ex_75GK3u3iHkO9
      :status: draft

      This noncompliant example uses direct equality, ordering, and address comparisons
      on function pointers.

      .. rust-example::

          #![allow(unpredictable_function_pointer_comparisons)]

          fn handler_a() {}
          fn handler_b() {}

          fn main() {
              let f1: fn() = handler_a;
              let f2: fn() = handler_b;

              if f1 == f2 {
                  println!("same");
              }

              if f1 < f2 {
                  println!("ordered");
              }

              let addr1 = f1 as usize;
              let addr2 = f2 as usize;
              if addr1 == addr2 {
                  println!("same address");
              }

              let _ = matches!(f1, f if f == handler_a);
              assert_ne!(f1, f2);
          }

   .. non_compliant_example::
      :id: non_compl_ex_rrPRKq8Gsinn
      :status: draft

      This noncompliant example assumes address identity for non-``#[no_mangle]`` functions.
      It relies on function pointer equality after transmuting a raw address.

      .. rust-example::
          :miri: skip

          #[repr(align(4))]
          union MyMaybeUninit {
              uninit: (),
              init: (u8, u8, u8, u8),
          }

          #[no_mangle]
          fn write_first(a: &mut MyMaybeUninit) {
              *a = MyMaybeUninit { init: (0, 1, 2, 3) };
              *a = MyMaybeUninit { uninit: () };
              a.init.0 = 0;
              a.init.1 = 1;
              a.init.3 = 3;
          }

          #[no_mangle]
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
                      let ptr = addr1 as *const ();
                      let f: fn(&mut MyMaybeUninit) = core::mem::transmute(ptr);
                      f(&mut a);
                  }
              }
              unsafe { a.init }
          }

          fn main() {
              println!("{:?}", get_a());
          }

   .. non_compliant_example::
      :id: non_compl_ex_hRtB7qAhhae5
      :status: draft

      This noncompliant example compares functions across module boundaries. In real builds,
      the same function can be instantiated multiple times across crates.

      .. rust-example::

          #![allow(unpredictable_function_pointer_comparisons)]

          mod crate_a {
              pub fn handler_a() {}
              pub fn handler_b() {}
          }

          fn dispatch(f: fn()) {
              if f == crate_a::handler_a {
                  println!("Handled by A");
              } else if f == crate_a::handler_b {
                  println!("Handled by B");
              }
          }

          fn main() {
              dispatch(crate_a::handler_a);
          }

   .. non_compliant_example::
      :id: non_compl_ex_QQcHWm3RVUlE
      :status: draft

      This noncompliant example uses function pointers as identity keys in collections.

      .. rust-example::

          use std::collections::{HashMap, HashSet};

          fn handler() {}

          fn main() {
              let mut handlers: Vec<fn()> = Vec::new();
              if !handlers.contains(&(handler as fn())) {  // noncompliant
                  handlers.push(handler);
              }
              handlers.sort();
              handlers.dedup();

              let mut set: HashSet<fn()> = HashSet::new();
              set.insert(handler);
              let _ = set.contains(&(handler as fn()));

              let mut registry: HashMap<fn(), &'static str> = HashMap::new();
              registry.insert(handler, "handler");
              let _ = registry.get(&(handler as fn()));
          }

   .. compliant_example::
      :id: compl_ex_iMDVArZsSG5u
      :status: draft

      Replace function pointer comparison with an explicit enumeration type.

      .. rust-example::

          mod crate_a {
              #[derive(Copy, Clone)]
              pub enum HandlerId { A, B }

              pub fn handler_a() {}
              pub fn handler_b() {}

              pub fn dispatch(id: HandlerId) {
                  match id {
                      HandlerId::A => handler_a(),
                      HandlerId::B => handler_b(),
                  }
              }
          }

          fn main() {
              crate_a::dispatch(crate_a::HandlerId::A);
              crate_a::dispatch(crate_a::HandlerId::B);
          }

   .. compliant_example::
      :id: compl_ex_3fkJW0jFCDaR
      :status: draft

      Use stable, programmer-defined identifiers as identity keys.

      .. rust-example::

          use std::collections::HashMap;

          fn op_mul(x: i32) -> i32 { x * 2 }
          fn op_add(x: i32) -> i32 { x + 2 }

          #[derive(Copy, Clone)]
          struct Operation {
              id: u32,
              func: fn(i32) -> i32,
          }

          const OP_MUL: Operation = Operation { id: 1, func: op_mul };
          const OP_ADD: Operation = Operation { id: 2, func: op_add };

          fn main() {
              let mut registry: HashMap<u32, &'static str> = HashMap::new();
              registry.insert(OP_MUL.id, "double");
              registry.insert(OP_ADD.id, "increment");

              let op = OP_MUL;
              let result = (op.func)(10);
              println!("result = {}", result);
              let _ = registry.get(&op.id);
          }

   .. bibliography::
      :id: bib_mYsPfo39J8pv
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_xUv7u4w6I7Oi:RUST-ISSUE-117047`
           - The Rust Project Developers. "Function pointer comparison fails unexpectedly." https://github.com/rust-lang/rust/issues/117047
         * - :bibentry:`gui_xUv7u4w6I7Oi:RUST-REF-NO-MANGLE`
           - The Rust Project Developers. "The no_mangle Attribute." https://doc.rust-lang.org/reference/abi.html#the-no_mangle-attribute
         * - :bibentry:`gui_xUv7u4w6I7Oi:RUST-REF-FN-PTR`
           - The Rust Project Developers. "Function Pointer Types." https://doc.rust-lang.org/reference/types/function-pointer.html
         * - :bibentry:`gui_xUv7u4w6I7Oi:FLS`
           - Ferrocene Developers. "Ferrocene Language Specification." https://spec.ferrocene.dev/
         * - :bibentry:`gui_xUv7u4w6I7Oi:LLVM-LTO`
           - LLVM Project. "LLVM Link Time Optimization: Design and Implementation." https://llvm.org/docs/LinkTimeOptimization.html
