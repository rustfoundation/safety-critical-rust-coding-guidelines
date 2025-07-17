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

.. guideline:: Do not divide by 0
   :id: gui_kMbiWbn8Z6g5
   :category: mandatory
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: undecidable
   :scope: system
   :tags: numerics

   This guideline applies when unsigned integer or two’s complement division is performed during the
   evaluation of an `ArithmeticExpression
   <https://rust-lang.github.io/fls/expressions.html#arithmetic-expressions>`_.

   Note that this includes the evaluation of a `RemainderExpression
   <https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression>`_, which uses unsigned integer or two's
   complement division.

   This rule does not apply to evaluation of a :std:`core::ops::Div` trait on types other than `integer
   types <https://rust-lang.github.io/fls/types-and-traits.html#integer-types>`_. The use of
   :std:`std::num::NonZero` or is therefore a recommended way to avoid the undecidability of this
   guideline.

   .. rationale::
      :id: rat_h84NjY2tLSBW
      :status: draft

      Integer division by zero results in a panic, which is an abnormal program state and may terminate the process.

   .. non_compliant_example::
      :id: non_compl_ex_LLs3vY8aGz0F
      :status: draft

      When the division is performed, the right operand is evaluated to zero and the program panics.

      .. code-block:: rust

         let x = 0;
         let x = 5 / x;

   .. compliant_example::
      :id: compl_ex_Ri9pP5Ch3kbb
      :status: draft

      There is no compliant way to perform integer division by zero. A checked division will prevent any
      division by zero from happening. The programmer can then handle the returned :std:``std::option::Option``.

      .. code-block:: rust

         let x = 5u8.checked_div(0);
