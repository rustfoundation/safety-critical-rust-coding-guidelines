.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Expressions
===========


.. guideline:: Avoid as underscore pointer casts
   :id: gui_HDnAZ7EZ4z6G
   :category: required
   :status: draft
   :release: <TODO>
   :fls: fls_1qhsun1vyarz
   :decidability: decidable
   :scope: module
   :tags: readability, reduce-human-error

   Code must not rely on Rust's type inference when doing explicit pointer casts via ``var as Type`` or ``core::mem::transmute``.
   Instead, explicitly specify the complete target type in the ``as`` expression or ``core::mem::transmute`` call expression.

   .. rationale::
      :id: rat_h8LdJQ1MNKu9
      :status: draft

      ``var as Type`` casts and ``core::mem::transmute``\s between raw pointer types are generally valid and unchecked by the compiler as long the target pointer type is a thin pointer.
      Not specifying the concrete target pointer type allows the compiler to infer it from the surroundings context which may result in the cast accidentally changing due to surrounding type changes resulting in semantically invalid pointer casts.

      Raw pointers have a variety of invariants to manually keep track of.
      Specifying the concrete types in these scenarios allows the compiler to catch some of these potential issues for the user.

   .. non_compliant_example::
      :id: non_compl_ex_V37Pl103aUW4
      :status: draft

      The following code leaves it up to type inference to figure out the concrete types of the raw pointer casts, allowing changes to ``with_base``'s function signature to affect the types the function body of ``non_compliant_example`` without incurring a compiler error.

      .. code-block:: rust

         #[repr(C)]
         struct Base {
            position: (u32, u32)
         }

         #[repr(C)]
         struct Extended {
            base: Base,
            scale: f32
         }

         fn non_compliant_example(extended: &Extended) {
            let extended = extended as *const _;
            with_base(unsafe { &*(extended as *const _) })
         }

         fn with_base(_: &Base) { ... }

   .. compliant_example::
      :id: compl_ex_W08ckDrkOhkt
      :status: draft

      We specify the concrete target types for our pointer casts resulting in a compilation error if the function signature of ``with_base`` is changed.

      .. code-block:: rust

         #[repr(C)]
         struct Base {
            position: (u32, u32)
         }

         #[repr(C)]
         struct Extended {
            base: Base,
            scale: f32
         }

         fn non_compliant_example(extended: &Extended) {
            let extended = extended as *const Extended;
            with_base(unsafe { &*(extended as *const Base) })
         }

         fn with_base(_: &Base) { ... }

.. guideline:: Do not use integer type as divisor
   :id: gui_7y0GAMmtMhch
   :category: required
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: decidable
   :scope: module
   :tags: numerics

   This guideline applies when a `Division Expression
   <https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression>`_ or `RemainderExpression
   <https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression>`_ is used with a RightOperand of
   `integer type <https://rust-lang.github.io/fls/types-and-traits.html#integer-types>`_.

   .. rationale::
      :id: rat_vLFlPWSCHRje
      :status: draft

      The built-in semantics for these expressions can result in panics when division by zero occurs. It is
      recommended to either use checked arithmetic functions to explicitly specify the behavior in such
      situations or to use :std:`std::num::NonZero` as a divisor to avoid division by zero.

   .. non_compliant_example::
      :id: non_compl_ex_0XeioBrgfh5z
      :status: draft

      When the division is performed, the right operand is evaluated to zero and the program panics.

      .. code-block:: rust

         let x = 0;
         let x = 5 / x;

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXb
      :status: draft

      The developer must explicitly indicate the intended behavior when a division by zero occurs, or use a
      type for which it is invalid to have a value of zero.

      .. code-block:: rust

         let x = 0;
         let result = match 5u32.checked_div(x) {
           None => 0
           Some(r) => r
         }
         if let Some(divisor) = match NonZero::<u32>::new(x) {
           let result = 5 / divisor;
         }
