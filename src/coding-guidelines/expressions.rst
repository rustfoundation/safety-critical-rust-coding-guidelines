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

.. guideline:: Do not use builtin integer arithmetic expressions
   :id: gui_7y0GAMmtMhch
   :category: required
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: decidable
   :scope: module
   :tags: numerics

   This guideline applies when an `ArithmeticExpression
   <https://rust-lang.github.io/fls/expressions.html#arithmetic-expressions>`_ is used with operands of
   integer type.

   .. rationale::
      :id: rat_vLFlPWSCHRje
      :status: draft

      The built-in semantics for these expressions can result in panics, or silent wrap around upon overflow
      or division by zero occurs. It is recommended to explicitly declare what should happen during these
      events with checked arithmetic functions.

   .. non_compliant_example::
      :id: non_compl_ex_0XeioBrgfh5z
      :status: draft

      When the division is performed, the right operand is evaluated to zero and the program panics.
      When the addition is performed, either silent overflow happens or a panic depending on the build
      configuration.

      .. code-block:: rust

         let x = 0;
         let x = 5 / x;
         let y = 135u8
         let y = 200u8 + y;

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXb
      :status: draft

      The developer must explicitly indicate the intended behavior when a division by zero or arithmetic
      overflow occurs when using checked arithmetic methods.

      .. code-block:: rust

         let x = 0;
         let result = match 5u32.checked_div(x) {
            None => 0
            Some(r) => r
         }
         let y = 135u8
         let y = 200u8.wrapping_add(y);

.. guideline:: Do not use unchecked integer arithmetic methods
   :id: gui_mNEvznFjC3kG
   :category: advisory
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: decidable
   :scope: module
   :tags: numerics

   This guideline applies to any call to the integer type methods that begin with ``unchecked_``, such as
   `core::primitive::u8::unchecked_add <https://doc.rust-lang.org/std/primitive.u8.html#method.unchecked_add>`_.

   .. rationale::
      :id: rat_7tF18FIwSYws
      :status: draft

      The semantics for these expressions can result in undefined behavior in situations where an equivalent
      checked operation would return ``None``. It is recommended to explicitly declare what should happen
      during these events with checked arithmetic functions.

      In a particularly performance sensitive critical section of the code it may be necessary to use the
      unchecked methods in tandem with assurances that the arguments will never meet the panic conditions.

   .. non_compliant_example::
      :id: non_compl_ex_JeRRIgVjq8IE
      :status: draft

      When the multiplication is performed, the evaluation could result in undefined behavior.

      .. code-block:: rust

         let x = 13u8.unchecked_mul(y);

   .. compliant_example::
      :id: compl_ex_HIBS9PeBa41c
      :status: draft

      If arithmetic overflow would have occurred during the multiplication operation this method will ensure
      that the returned value is the bounding of the type. The intention is clear in that case.

      .. code-block:: rust

         let x = 13u8.saturating_mul(y);

