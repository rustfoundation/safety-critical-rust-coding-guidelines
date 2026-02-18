.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Do not directly or indirectly compare function pointers
=======================================================

.. guideline:: Do not *directly* or *indirectly* compare function pointers
   :id: gui_QbvIknd9qNF6
   :category: required
   :status: draft
   :release: unclear-latest
   :fls: fls_1kg1mknf4yx7
   :decidability: decidable
   :scope: system
   :tags: surprising-behavior

   Do not *directly* or *indirectly* compare function pointers.

   **Direct Equality (``==``, ``!=``)**

   .. rust-example::
      :no_run:

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler_a() {}
      fn handler_b() {}

      fn main() {
          let fn_ptr1: fn() = handler_a;
          let fn_ptr2: fn() = handler_b;

          if fn_ptr1 == fn_ptr2 {
              println!("same");
          }
      }

   The following are all the ways function pointers can be indirectly compared:

   **Collection Membership**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      use std::collections::{BTreeSet, HashSet};

      fn handler() {}

      fn main() {
          let mut handlers: Vec<fn()> = Vec::new();
          handlers.push(handler);
          let _ = handlers.contains(&(handler as fn()));

          let mut set: HashSet<fn()> = HashSet::new();
          set.insert(handler);
          let _ = set.contains(&(handler as fn()));

          let mut tree: BTreeSet<fn()> = BTreeSet::new();
          tree.insert(handler);
          let _ = tree.contains(&(handler as fn()));
      }

   **HashMap/BTreeMap Keys**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      use std::collections::{BTreeMap, HashMap};

      fn handler() {}

      fn main() {
          let mut map: HashMap<fn(), &str> = HashMap::new();
          map.insert(handler, "name");
          let _ = map.get(&(handler as fn()));

          let mut tree: BTreeMap<fn(), &str> = BTreeMap::new();
          tree.insert(handler, "name");
          let _ = tree.get(&(handler as fn()));
      }

   **Ordering Comparisons (``<``, ``>``, ``<=``, ``>=``)**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler_a() {}
      fn handler_b() {}

      fn main() {
          let fn_ptr1: fn() = handler_a;
          let fn_ptr2: fn() = handler_b;

          if fn_ptr1 < fn_ptr2 {
              println!("ordered");
          }
      }

   **Sorting & Binary Search**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler_a() {}
      fn handler_b() {}

      fn main() {
          let mut fns: Vec<fn()> = vec![handler_a, handler_b];
          fns.sort();

          let handler: fn() = handler_a;
          let _ = fns.binary_search(&handler);
      }

   **Deduplication**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler() {}

      fn main() {
          let mut fns: Vec<fn()> = vec![handler, handler];
          fns.sort();
          fns.dedup();
          let _ = fns.len();
      }

   **Iterator Methods**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler_a() {}
      fn handler_b() {}

      fn main() {
          let handlers: Vec<fn()> = vec![handler_a, handler_b];
          let handler: fn() = handler_a;

          let _ = handlers.iter().find(|&&f| f == handler);
          let _ = handlers.iter().position(|&f| f == handler);
          let _ = handlers.iter().any(|&f| f == handler);
          let _ = handlers.iter().filter(|&&f| f == handler).count();
      }

   **Pattern Matching**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler_a() {}
      fn handler_b() {}

      fn main() {
          let callback: fn() = handler_a;

          match callback {
              f if f == handler_a => println!("A"),
              f if f == handler_b => println!("B"),
              _ => println!("other"),
          }
      }

   **Casting to ``usize``**

   .. rust-example::

      fn handler_a() {}
      fn handler_b() {}

      fn main() {
          let fn_ptr1: fn() = handler_a;
          let fn_ptr2: fn() = handler_b;

          let addr1 = fn_ptr1 as usize;
          let addr2 = fn_ptr2 as usize;
          if addr1 == addr2 {
              println!("same address");
          }
      }

   **Assertion Macros**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler_a() {}

      fn main() {
          let fn_ptr1: fn() = handler_a;
          let fn_ptr2: fn() = handler_a;

          assert_eq!(fn_ptr1, fn_ptr2);
          debug_assert_ne!(fn_ptr1, fn_ptr2);
      }

   **``matches!`` Macro**

   .. rust-example::

      #![allow(unpredictable_function_pointer_comparisons)]

      fn handler() {}

      fn main() {
          let callback: fn() = handler;
          let _ = matches!(callback, f if f == handler);
      }

   **Exception**

   ``#[no_mangle]`` functions are guaranteed to have a single instance
   :cite:`gui_QbvIknd9qNF6:RUST-REF-NO-MANGLE`.

   .. rationale::
      :id: rat_kYiIiW8R2qD3
      :status: draft

      Functions may be instantiated multiple times. They may, for example, be instantiated
      every time they are referenced. Only ``#[no_mangle]`` functions are guaranteed to be
      instantiated a single time, but can cause undefined behavior if they share a symbol
      with other identifiers.

      Avoid assumptions about low-level metadata (such as symbol addresses) unless
      explicitly guaranteed by the Ferrocene Language Specification
      :cite:`gui_QbvIknd9qNF6:FLS`.
      Function address identity is not guaranteed and must not be treated as stable.
      Rust's ``fn`` type is a zero-sized function item promoted to a function pointer
      :cite:`gui_QbvIknd9qNF6:RUST-REF-FN-PTR`, whose address is determined by the compiler
      backend. When a function resides in a different crate or codegen-unit partitioning is
      enabled, the compiler may generate multiple distinct code instances for the same
      function or alter the address at which it is emitted.

      Consequently, the following operations are unreliable for functions which are not
      ``#[no_mangle]``:

      - Comparing function pointers for equality (``fn1 == fn2``)
      - Assuming a unique function address
      - Using function pointers as identity keys (e.g., in maps, registries, matchers)
      - Matching behavior based on function address unless you instruct the linker to put a
        ``#[no_mangle]`` function at a specific address

      This rule applies even when the functions are semantically identical, exported as
      ``pub``, or defined once in source form.

      .. rationale::
         :id: rat_xcVE5Hfnbb2u
         :status: draft

         Compiler optimizations may cause function pointers to lose stable identity, for example:

         - Cross-crate inlining can produce multiple code instantiations
         - Codegen-unit separation can cause function emission in multiple codegen units
         - Function implementations may be merged as an optimization
           :cite:`gui_QbvIknd9qNF6:LLVM-LTO`.

         Functions that are equivalent based only on specific hardware semantics may be merged in
         the machine-specific backend. For example:

         .. rust-example::
            :miri: skip

            #[no_mangle]
            fn foo(x: *mut i32, y: *mut i32) {
                unsafe {
                    let a = &mut *x;
                    let b = &mut *y;
                    *a = *b;
                }
            }

            #[no_mangle]
            fn bar(x: *mut i32, y: *mut i32) {
                unsafe {
                    x.write(y.read());
                }
            }

            fn main() {
                let mut x1 = 0i32;
                let mut y1 = 42i32;
                foo(&mut x1, &mut y1);
                println!("foo: x1 = {}, y1 = {}", x1, y1);

                let mut x2 = 0i32;
                let mut y2 = 42i32;
                bar(&mut x2, &mut y2);
                println!("bar: x2 = {}, y2 = {}", x2, y2);
            }

         These functions are deduplicated for specific backends and have the same address. This
         happened even though these two functions have different behavior in the abstract machine:
         the ``foo`` function has undefined behavior if ``x`` and ``y`` alias, while the ``bar``
         function does not.

         This behavior has resulted in real-world issues, such as the bug reported in
         :cite:`gui_QbvIknd9qNF6:RUST-ISSUE-117047`, where function pointer comparisons
         unexpectedly failed because the function in question was instantiated multiple times.

         Violating this rule may cause:

         - Silent logic failures: callbacks not matching, dispatch tables misbehaving.
         - Inappropriate branching: identity-based dispatch selecting wrong handler.
         - Security issues: adversary-controlled conditions bypassing function-based
           authorization or dispatch logic.
         - Nondeterministic behavior: correctness depending on build flags or incremental state.
         - Test-only correctness: function pointer equality passing in debug builds but failing in
           release or link-time optimization builds.

         In summary, dependence on function address stability introduces non-portable,
         build-profile-dependent behavior, which is incompatible with high-integrity Rust.

   .. non_compliant_example::
      :id: non_compl_ex_MkAkFxjRTijy
      :status: draft

      In this noncompliant example, the ``write_first`` and ``write_second`` functions each
      initialize one field within a ``MaybeUninit`` and write ``uninit`` to the other. If
      those addresses are equal, the code at that address must initialize both fields.
      In that case it should be sound to call a function pointer created from that address and
      assume that both fields were initialized, even though you did not write any such function.

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
              let addr1 = write_first as *const ();
              let addr2 = write_second as *const ();
              if addr1 == addr2 {
                  unsafe {
                      let f: fn(&mut MyMaybeUninit) = core::mem::transmute(addr1);
                      f(&mut a);
                  }
              }
              unsafe { a.init }
          }

          fn main() {
              println!("{:?}", get_a());
          }

   .. non_compliant_example::
      :id: non_compl_ex_MkAkFxjRTijx
      :status: draft

      Due to cross-crate inlining or codegen-unit partitioning, the address of
      ``handler_a`` in crate ``B`` may differ from its address in crate ``A``,
      causing comparisons to fail as shown in this noncompliant example:

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

   .. compliant_example::
      :id: compl_ex_oiqSSclTXmIi
      :status: draft

      Replace function pointer comparison with an explicit enumeration type as shown in this
      compliant example:

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

   .. non_compliant_example::
      :id: non_compl_ex_lvEMJF5QkEEB
      :status: draft

      A function pointer used as a key is not guaranteed to have stable identity, as shown in
      this noncompliant example:

      .. rust-example::

          #![allow(unpredictable_function_pointer_comparisons)]

          use std::collections::HashMap;

          fn op_mul(x: i32) -> i32 { x * 2 }

          fn main() {
              let mut registry: HashMap<fn(i32) -> i32, &'static str> = HashMap::new();
              registry.insert(op_mul, "double");

              let f: fn(i32) -> i32 = op_mul;
              let _ = registry.get(&f);
          }

   .. compliant_example::
      :id: compl_ex_oiqSSclTXmIj
      :status: draft

      This compliant example uses stable identity wrappers as identity keys. The ``id`` is
      a stable, programmer-defined identity, immune to compiler optimizations. The function
      pointer is preserved for behavior (``func``) but never used as the identity key.

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

   .. non_compliant_example::
      :id: non_compl_ex_MkAkFxjRTijz
      :status: draft

      This noncompliant example relies on function pointer identity for deduplication:

      .. rust-example::

          #![allow(unpredictable_function_pointer_comparisons)]

          fn handler() {
              println!("handler called");
          }

          fn register(handlers: &mut Vec<fn()>, h: fn()) {
              if !handlers.contains(&h) {  // noncompliant
                  handlers.push(h);
              }
          }

          fn main() {
              let mut handlers: Vec<fn()> = Vec::new();
              register(&mut handlers, handler);
          }

   .. bibliography::
      :id: bib_Oy2dpXATgnxI
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_QbvIknd9qNF6:RUST-ISSUE-117047`
           - The Rust Project Developers. "Function pointer comparison fails unexpectedly." https://github.com/rust-lang/rust/issues/117047
         * - :bibentry:`gui_QbvIknd9qNF6:RUST-REF-NO-MANGLE`
           - The Rust Project Developers. "The no_mangle Attribute." https://doc.rust-lang.org/reference/abi.html#the-no_mangle-attribute
         * - :bibentry:`gui_QbvIknd9qNF6:RUST-REF-FN-PTR`
           - The Rust Project Developers. "Function Pointer Types." https://doc.rust-lang.org/reference/types/function-pointer.html
         * - :bibentry:`gui_QbvIknd9qNF6:FLS`
           - Ferrocene Developers. "Ferrocene Language Specification." https://spec.ferrocene.dev/
         * - :bibentry:`gui_QbvIknd9qNF6:LLVM-LTO`
           - LLVM Project. "LLVM Link Time Optimization: Design and Implementation." https://llvm.org/docs/LinkTimeOptimization.html
         * - :bibentry:`gui_QbvIknd9qNF6:RUST-RFC-2603`
           - The Rust Project Developers. "RFC 2603: Rust Symbol Name Mangling v0." https://rust-lang.github.io/rfcs/2603-rust-symbol-name-mangling-v0.html
         * - :bibentry:`gui_QbvIknd9qNF6:RUSTONOMICON-FFI`
           - The Rust Project Developers. "Foreign Function Interface." https://doc.rust-lang.org/nomicon/ffi.html
