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

   Code must not rely on Rust's type inference when doing explicit pointer casts via ``var as Type`` or :std:`core::mem::transmute`.
   Instead, explicitly specify the complete target type in the ``as`` expression or :std:`core::mem::transmute` call expression.

   .. rationale::
      :id: rat_h8LdJQ1MNKu9
      :status: draft

      ``var as Type`` casts and :std:`core::mem::transmute`\s between raw pointer types are generally valid and unchecked by the compiler as long the target pointer type is a thin pointer.
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
   :category: advisory
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: decidable
   :scope: module
   :tags: numerics, subset

   This guideline applies when a `DivisionExpression
   <https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression>`_ or `RemainderExpression
   <https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression>`_ is used with a RightOperand of
   `integer type <https://rust-lang.github.io/fls/types-and-traits.html#integer-types>`_.

   .. rationale::
      :id: rat_vLFlPWSCHRje
      :status: draft

      The built-in semantics for these expressions can result in panics when division by zero occurs. It is
      recommended to either:

      * Use checked division functions, which ensure the programmer handles the case when the divisor is zero, or
      * To create divisors using :std:`std::num::NonZero`, which then allows the programmer to perform those
        operations knowing that their divisor is not zero.

      **Note:** since the compiler can assume the value of a :std:`std::num::NonZero`
      variable to not be zero, checks for zero when dividing by it can be elided in the
      final binary, increasing overall performance beyond what normal division can have.

   .. non_compliant_example::
      :id: non_compl_ex_0XeioBrgfh5z
      :status: draft

      When either the division or remainder are performed, the right operand is evaluated to zero and the
      program panics.

      .. code-block:: rust

         let x = 0;
         let y = 5 / x; // This line will panic.
         let z = 5 % x; // This line would also panic.

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXb
      :status: draft

      There is no compliant way to divide with an integer type. Here, instead, the developer explicitly:

      * Uses a checked division function, which ensures a zero divisor is handled separately, and
      * Creates a divisor using :std:`std::num::NonZero`, which outsources the check for zero to the
        construction of that struct. It's worth noting that such a divisor can be used multiple times after it's been created, whilst keeping the guarantee that such divisions will be safe.

      .. code-block:: rust

         let x = 0;
         if let Some(divisor) = match NonZero::<u32>::new(x) {
           let result = 5 / divisor;
         }
         let result = match 5u32.checked_rem(x) {
           None => 0,
           Some(r) => r,
         }


.. guideline:: Do not divide by 0
   :id: gui_kMbiWbn8Z6g5
   :category: required
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: undecidable
   :scope: system
   :tags: numerics, defect

   This guideline applies when unsigned integer or two’s complement division is performed during the
   evaluation of an `ArithmeticExpression
   <https://rust-lang.github.io/fls/expressions.html#arithmetic-expressions>`_.

   This includes the evaluation of a `RemainderExpression
   <https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression>`_, which uses unsigned integer or two's
   complement division.

   This rule does not apply to evaluation of a :std:`core::ops::Div` trait on types other than `integer
   types <https://rust-lang.github.io/fls/types-and-traits.html#integer-types>`_.

   .. rationale::
      :id: rat_h84NjY2tLSBW
      :status: draft

      Integer division by zero results in a panic, which is an abnormal program state and may terminate the
      process. The use of :std:`std::num::NonZero` as the divisor is a recommended way to avoid the
      undecidability of this guideline.

   .. non_compliant_example::
      :id: non_compl_ex_LLs3vY8aGz0F
      :status: draft

      When the division is performed, the right operand is evaluated to zero and the program panics.

      .. code-block:: rust

         let x = 0;
         let y = 5 / x; // This line will panic.

   .. compliant_example::
      :id: compl_ex_Ri9pP5Ch3kbb
      :status: draft

      There is no compliant way to perform integer division by zero. A checked division will prevent any
      division by zero from happening. The programmer can then handle the returned :std:`std::option::Option`.

      The check for zero can also be performed manually. However, as the complexity of the control
      flow leading to the invariant increases, it becomes increasingly harder to reason about it. For both programmers and static analysis tools.

      .. code-block:: rust

         // Example 1: using the checked division API
         let result = match 5u8.checked_div(0) {
             None => 0
             Some(r) => r
         };
         
         // Example 2: performing zero-checks by hand
         let x = 0;
         let y = if x != 0 {
             5 / x
         } else {
             0
         };




.. guideline:: The 'as' operator should not be used with numeric operands
   :id: gui_ADHABsmK9FXz
   :category: advisory
   :status: draft
   :release: <TODO>
   :fls: fls_otaxe9okhdr1
   :decidability: decidable
   :scope: module
   :tags: subset, reduce-human-error

   The binary operator ``as`` should not be used with:

   * a numeric type, including all supported integer, floating, and machine-dependent arithmetic types; or
   * ``bool``; or
   * ``char``

   as either the right operand or the type of the left operand.

   **Exception:** ``as`` may be used with ``usize`` as the right operand and an expression of raw pointer
   type as the left operand.

   .. rationale::
      :id: rat_v56bjjcveLxQ
      :status: draft

      Although the conversions performed by ``as`` between numeric types are all well-defined, ``as`` coerces
      the value to fit in the destination type, which may result in unexpected data loss if the value needs to
      be truncated, rounded, or produce a nearest possible non-equal value.

      Although some conversions are lossless, others are not symmetrical. Instead of relying on either a defined
      lossy behaviour or risking loss of precision, the code can communicate intent by using ``Into`` or ``From``
      and ``TryInto`` or ``TryFrom`` to signal which conversions are intended to perfectly preserve the original
      value, and which are intended to be fallible. The latter cannot be used from const functions, indicating
      that these should avoid using fallible conversions.

      A pointer-to-address cast does not lose value, but will be truncated unless the destination type is large
      enough to hold the address value. The ``usize`` type is guaranteed to be wide enough for this purpose.

      A pointer-to-address cast is not symmetrical because the resulting pointer may not point to a valid object,
      may not point to an object of the right type, or may not be properly aligned.
      If a conversion in this direction is needed, :std:`std::mem::transmute` will communicate the intent to perform
      an unsafe operation.

   .. non_compliant_example::
      :id: non_compl_ex_hzGUYoMnK59w
      :status: draft

      ``as`` used here can change the value range or lose precision.
      Even when it doesn't, nothing enforces the correct behaviour or communicates whether
      we intend to allow lossy conversions, or only expect valid conversions.

      .. code-block:: rust

         fn f1(x: u16, y: i32, z: u64, w: u8) {
           let a = w as char;           // non-compliant
           let b = y as u32;            // non-compliant - changes value range, converting negative values
           let c = x as i64;            // non-compliant - could use .into()

           let d = y as f32;            // non-compliant - lossy
           let e = d as f64;            // non-compliant - could use .into()
           let f = e as f32;            // non-compliant - lossy

           let g = e as i64;            // non-compliant - lossy despite object size

           let p1: * const u32 = &b;
           let a1 = p1 as usize;        // compliant by exception
           let a2 = p1 as u16;          // non-compliant - may lose address range
           let a3 = p1 as u64;          // non-compliant - use usize to indicate intent

           let p2 = a1 as * const u32;  // non-compliant - prefer transmute
           let p3 = a2 as * const u32;  // non-compliant (and most likely not in a valid address range)
         }

   .. compliant_example::
      :id: compl_ex_uilHTIOgxD37
      :status: draft

      Valid conversions that are guaranteed to preserve exact values can be communicated
      better with ``into()`` or ``from()``.
      Valid conversions that risk losing value, where doing so would be an error, can
      communicate this and include an error check, with ``try_into`` or ``try_from``.
      Other forms of conversion may find ``transmute`` better communicates their intent.

      .. code-block:: rust

         fn f2(x: u16, y: i32, z: u64, w: u8) {
           let a: char            = w.into();
           let b: Result <u32, _> = y.try_into(); // produce an error on range clip
           let c: i64             = x.into();

           let d = f32::from(x);  // u16 is within range, u32 is not
           let e = f64::from(d);
           // let f = f32::from(e); // no From exists

           // let g = ...            // no From exists

           let h: u32 = 0;
           let p1: * const u32 = &h;
           let a1 = p1 as usize;     // (compliant)

           unsafe {
             let a2: usize = std::mem::transmute(p1);  // OK
             let a3: u64   = std::mem::transmute(p1);  // OK, size is checked
             // let a3: u16   = std::mem::transmute(p1);  // invalid, different sizes

             let p2: * const u32 = std::mem::transmute(a1); // OK
             let p3: * const u32 = std::mem::transmute(a1); // OK
           }

           unsafe {
             // does something entirely different,
             // reinterpreting the bits of z as the IEEE bit pattern of a double
             // precision object, rather than converting the integer value
             let f1: f64 = std::mem::transmute(z);
           }
         }


.. guideline:: An integer shall not be converted to a pointer
   :id: gui_PM8Vpf7lZ51U
   :category: <TODO>
   :status: draft
   :release: <TODO>
   :fls: fls_59mpteeczzo
   :decidability: decidable
   :scope: module
   :tags: subset, undefined-behavior

   The ``as`` operator shall not be used with an expression of numeric type as the left operand,
   and any pointer type as the right operand.

   :std:`std::mem::transmute` shall not be used with any numeric type (including floating point types)
   as the argument to the ``Src`` parameter, and any pointer type as the argument to the ``Dst`` parameter.

   .. rationale::
      :id: rat_YqhEiWTj9z6L
      :status: draft

      A pointer created from an arbitrary arithmetic expression may designate an invalid address,
      including an address that does not point to a valid object, an address that points to an
      object of the wrong type, or an address that is not properly aligned. Use of such a pointer
      to access memory will result in undefined behavior.

      The ``as`` operator also does not check that the size of the source operand is the same as
      the size of a pointer, which may lead to unexpected results if the address computation was
      originally performed in a differently-sized address space.

      While ``as`` can notionally be used to create a null pointer, the functions
      :std:`core::ptr::null` and :std:`core::ptr::null_mut` are the more idiomatic way to do this.

   .. non_compliant_example::
      :id: non_compl_ex_0ydPk7VENSrA
      :status: draft

      Any use of ``as`` or ``transmute`` to create a pointer from an arithmetic address value
      is non-compliant:

      .. code-block:: rust

        fn f1(x: u16, y: i32, z: u64, w: usize) {
          let p1 = x as * const u32;  // not compliant
          let p2 = y as * const u32;  // not compliant
          let p3 = z as * const u32;  // not compliant
          let p4 = w as * const u32;  // not compliant despite being the right size

          let f: f64 = 10.0;
          // let p5 = f as * const u32;  // not valid

          unsafe {
            // let p5: * const u32 = std::mem::transmute(x);  // not valid
            // let p6: * const u32 = std::mem::transmute(y);  // not valid

            let p7: * const u32 = std::mem::transmute(z); // not compliant
            let p8: * const u32 = std::mem::transmute(w); // not compliant

            let p9: * const u32 = std::mem::transmute(f); // not compliant, and very strange
          }
        }

   .. compliant_example::
      :id: compl_ex_oneKuF52yzrx
      :status: draft

      There is no compliant example of this operation.


.. guideline:: An integer shall not be converted to an invalid pointer
   :id: gui_iv9yCMHRgpE0
   :category: <TODO>
   :status: draft
   :release: <TODO>
   :fls: fls_9wgldua1u8yt
   :decidability: undecidable
   :scope: system
   :tags: defect, undefined-behavior

   An expression of numeric type shall not be converted to a pointer if the resulting pointer
   is incorrectly aligned, does not point to an entity of the referenced type, or is an invalid representation.

   .. rationale::
      :id: rat_OhxKm751axKw
      :status: draft

      The mapping between pointers and integers must be consistent with the addressing structure of the
      execution environment. Issues may arise, for example, on architectures that have a segmented memory model.

   .. non_compliant_example::
      :id: non_compl_ex_CkytKjRQezfQ
      :status: draft

      This example makes assumptions about the layout of the address space that do not hold on all platforms.
      The manipulated address may have discarded part of the original address space, and the flag may
      silently interfere with the address value. On platforms where pointers are 64-bits this may have
      particularly unexpected results.

      .. code-block:: rust

        fn f1(flag: u32, ptr: * const u32) {
          /* ... */
          let mut rep = ptr as usize;
          rep = (rep & 0x7fffff) | ((flag as usize) << 23);
          let p2 = rep as * const u32;
        }

   .. compliant_example::
      :id: compl_ex_oBoluiKSvREu
      :status: draft

      This compliant solution uses a struct to provide storage for both the pointer and the flag value.
      This solution is portable to machines of different word sizes, both smaller and larger than 32 bits,
      working even when pointers cannot be represented in any integer type.

      .. code-block:: rust

        struct PtrFlag {
          pointer: * const u32,
          flag: u32
        }

        fn f2(flag: u32, ptr: * const u32) {
          let ptrflag = PtrFlag {
            pointer: ptr,
            flag: flag
          };
          /* ... */
        }


.. guideline:: Integer shift shall only be performed through `checked_` APIs
    :id: gui_RHvQj8BHlz9b 
    :category: required
    :status: draft
    :release: 1.7.0-latest
    :fls: fls_sru4wi5jomoe
    :decidability: decidable
    :scope: module
    :tags: numerics, reduce-human-error, maintainability, portability, surprising-behavior, subset

    In particular, the user should only perform left shifts via the `checked_shl <https://doc.rust-lang.org/core/index.html?search=%22checked_shl%22>`_ function and right shifts via the `checked_shr <https://doc.rust-lang.org/core/index.html?search=%22checked_shr%22>`_ function. Both of these functions exist in `core <https://doc.rust-lang.org/core/index.html>`_.

    This rule applies to the following primitive types:


    * ``i8``
    * ``i16``
    * ``i32``
    * ``i64``
    * ``i128``
    * ``u8``
    * ``u16``
    * ``u32``
    * ``u64``
    * ``u128``
    * ``usize``
    * ``isize``

    .. rationale:: 
        :id: rat_3MpR8QfHodGT 
        :status: draft

        This is a Subset rule, directly inspired by `INT34-C. Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the operand <https://wiki.sei.cmu.edu/confluence/x/ItcxBQ>`_.

        In Rust these out-of-range shifts don't give rise to Undefined Behavior; however, they are still problematic in Safety Critical contexts for two reasons.


        * 
          **Reason 1: inconsistent behavior**

          The behavior of shift operations depends on the compilation mode. Say for example, that we have a number ``x`` of type ``uN``\ , and we perform the operation

          ``x << M`` 

          Then, it will behave like this:

          +------------------+-----------------+-----------------------+-----------------------+
          | Compilation Mode | ``0 <= M < N``  | ``M < 0``             | ``N <= M``            |
          +==================+=================+=======================+=======================+
          | Debug            | Shifts normally | Panics                | Panics                |
          +------------------+-----------------+-----------------------+-----------------------+
          | Release          | Shifts normally | Shifts by ``M mod N`` | Shifts by ``M mod N`` |
          +------------------+-----------------+-----------------------+-----------------------+

          ..

             Note: the behavior is exactly the same for the ``>>`` operator.


          Panicking in ``Debug`` is an issue by itself, however, a perhaps larger issue there is that its behavior is different from that of ``Release``. Such inconsistencies aren't acceptable in Safety Critical scenarios.

          Therefore, a consistently-behaved operation should be required for performing shifts.

        * 
          **Reason 2: programmer intent**

          There is no scenario in which it makes sense to perform a shift of negative length, or of more than ``N - 1`` bits. The operation itself becomes meaningless.

          Therefore, an API that restricts the length of the shift to the range ``[0, N - 1]`` should be used instead of the ``<<`` and ``>>`` operators.

        * 
          **The Solution**

          The ideal solution for this exists in ``core``\ : ``checked_shl`` and ``checked_shr``.

          ``<T>::checked_shl(M)`` returns a value of type ``Option<T>``\ , in the following way:


          * If ``M < 0``\ , the output is ``None``
          * If ``0 <= M < N`` for ``T`` of ``N`` bits, then the output is ``Some(T)``
          * If ``N <= M``\ , the output is ``None``

          This API has consistent behavior across ``Debug`` and ``Release``\ , and makes the programmer intent explicit, which effectively solves this issue.

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcn 
        :status: draft

        As seen in the example below:


        * A ``Debug`` build **panics**\ , 
        * 
          Whereas a ``Release`` build prints the values:

          .. code-block::

             61 << -1 = 2147483648
             61 << 4 = 976
             61 << 40 = 15616

        This shows **Reason 1** prominently.

        **Reason 2** is not seen in the code, because it is a reason of programmer intent: shifts by less than 0 or by more than ``N - 1`` (N being the bit-length of the value being shifted) are both meaningless.

        .. code-block:: rust

            fn bad_shl(bits: u32, shift: i32) -> u32 {
               bits << shift
            }

            let bits : u32 = 61;
            let shifts = vec![-1, 4, 40];

            for sh in shifts {
               println!("{bits} << {sh} = {}", bad_shl(bits, sh));
            }

    .. compliant_example::
        :id: compl_ex_xpPQqYeEPGIo 
        :status: draft

        As seen in the example below:


        * Both ``Debug`` and ``Release`` give the same exact output, which addresses **Reason 1**.
        * Shifting by negative values is impossible due to the fact that ``checked_shl`` only accepts unsigned integers as shift lengths.
        * Shifting by more than ``N - 1`` (N being the bit-length of the value being shifted) returns a ``None`` value:
          .. code-block::

             61 << 4 = Some(976)
             61 << 40 = None

        The last 2 observations show how this addresses **Reason 2**.

        .. code-block:: rust

            fn good_shl(bits: u32, shift: u32) -> Option<u32> {
               bits.checked_shl(shift)
            }

            let bits : u32 = 61;
            // let shifts = vec![-1, 4, 40];
            //                    ^--- Would not typecheck, as checked_shl
            //                         only accepts positive shift amounts
            let shifts = vec![4, 40];

            for sh in shifts {
               println!("{bits} << {sh} = {:?}", good_shl(bits, sh));
            }
