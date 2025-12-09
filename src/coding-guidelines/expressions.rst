.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Expressions
===========


.. guideline:: Ensure that integer operations do not result in arithmetic overflow
    :id: gui_dCquvqE1csI3
    :category: required
    :status: draft
    :release: 1.0 - latest
    :fls: fls_oFIRXBPXu6Zv
    :decidability: decidable
    :scope: system
    :tags: security, performance, numerics

    Eliminate `arithmetic overflow <https://rust-lang.github.io/fls/expressions.html#arithmetic-overflow>`_ of both signed and unsigned integer types. 
    Any wraparound behavior must be explicitly specified to ensure the same behavior in both debug and release modes.

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
        :id: rat_LvrS1jTCXEOk
        :status: draft

        Eliminate arithmetic overflow to avoid runtime panics and unexpected wraparound behavior.
        Arithmetic overflow will panic in debug mode, but wraparound in release mode, resulting in inconsistent behavior.
        Use explicit `wrapping <https://doc.rust-lang.org/std/num/struct.Wrapping.html>`_ or
        `saturating <https://doc.rust-lang.org/std/num/struct.Saturating.html>`_ semantics where these behaviors are intentional.
        Range checking can be used to eliminate the possibility of arithmetic overflow.

    .. non_compliant_example::
        :id: non_compl_ex_cCh2RQUXeH0N
        :status: draft

        This noncompliant code example can result in arithmetic overflow during the addition of the signed operands ``si_a`` and ``si_b``:

        .. code-block:: rust

            fn add(si_a: i32, si_b: i32) {
              let sum: i32 = si_a + si_b;
              // ...
            }

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4b_1
        :status: draft

        This compliant solution ensures that the addition operation cannot result in arithmetic overflow,
        based on the maximum range of a signed 32-bit integer.
        Functions such as 
        `overflowing_add <https://doc.rust-lang.org/stable/core/primitive.u32.html#method.overflowing_add>`_,
        `overflowing_sub <https://doc.rust-lang.org/stable/core/primitive.u32.html#method.overflowing_sub>`_, and 
        `overflowing_mul <https://doc.rust-lang.org/stable/core/primitive.u32.html#method.overflowing_mul>`_
        can also be used to detect overflow.
        Code that invoked these functions would typically further restrict the range of possible values,
        based on the anticipated range of the inputs.

        .. code-block:: rust

            enum ArithmeticError {
                Overflow,
                DivisionByZero,
            }

            use std::i32::{MAX as INT_MAX, MIN as INT_MIN};

            fn add(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                if (si_b > 0 && si_a > INT_MAX - si_b)
                    || (si_b < 0 && si_a < INT_MIN - si_b)
                {
                    Err(ArithmeticError::Overflow)
                } else {
                    Ok(si_a + si_b)
                }
            }

            fn sub(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                if (si_b < 0 && si_a > INT_MAX + si_b)
                    || (si_b > 0 && si_a < INT_MIN + si_b)
                {
                    Err(ArithmeticError::Overflow)
                } else {
                    Ok(si_a - si_b)
                }
            }

            fn mul(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                if si_a == 0 || si_b == 0 {
                    return Ok(0);
                }

                // Detect overflow before performing multiplication
                if (si_a == -1 && si_b == INT_MIN) || (si_b == -1 && si_a == INT_MIN) {
                    Err(ArithmeticError::Overflow)
                } else if (si_a > 0 && (si_b > INT_MAX / si_a || si_b < INT_MIN / si_a))
                    || (si_a < 0 && (si_b > INT_MIN / si_a || si_b < INT_MAX / si_a))
                {
                    Err(ArithmeticError::Overflow)
                } else {
                    Ok(si_a * si_b)
                }
            }

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4c
        :status: draft

        This compliant example uses safe checked addition instead of manual bounds checks.
        Checked functions can reduce readability when complex arithmetic expressions are needed.

        .. code-block:: rust

            fn add(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                si_a.checked_add(si_b).ok_or(ArithmeticError::Overflow)
            }

            fn sub(a: i32, b: i32) -> Result<i32, ArithmeticError> {
                a.checked_sub(b).ok_or(ArithmeticError::Overflow)
            }

            fn mul(a: i32, b: i32) -> Result<i32, ArithmeticError> {
                a.checked_mul(b).ok_or(ArithmeticError::Overflow)
            }

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4b
        :status: draft

        Wrapping behavior must be explicitly requested. This compliant example uses wrapping functions.

        .. code-block:: rust

            fn add(a: i32, b: i32) -> i32 {
                a.wrapping_add(b)
            }

            fn sub(a: i32, b: i32) -> i32 {
                a.wrapping_sub(b)
            }

            fn mul(a: i32, b: i32) -> i32 {
                a.wrapping_mul(b)
            }

    .. compliant_example::
        :id: compl_ex_BhUHiRB4kc4b
        :status: draft

        Wrapping behavior call also be achieved using the ``Wrapping<T>`` type as in this compliant solution.
        The ``Wrapping<T>`` type is a ``struct`` found in the ``std::num`` module that explicitly enables two's complement
        wrapping arithmetic for the inner type ``T`` (which must be an integer or ``usize/isize``). 
        The ``Wrapping<T>`` type provides a consistent way to force wrapping behavior in all build modes,
        which is useful in specific scenarios like implementing cryptography or hash functions where wrapping arithmetic is the intended behavior.

        .. code-block:: rust

            use std::num::Wrapping;

            fn add(si_a: Wrapping<i32>, si_b: Wrapping<i32>) -> Wrapping<i32> {
                si_a + si_b
            }

            fn sub(si_a: Wrapping<i32>, si_b: Wrapping<i32>) -> Wrapping<i32> {
                si_a - si_b
            }

            fn mul(si_a: Wrapping<i32>, si_b: Wrapping<i32>) -> Wrapping<i32> {
                si_a * si_b
            }

            fn main() {    
                let si_a = Wrapping(i32::MAX);
                let si_b = Wrapping(i32::MAX);
                println!("{} + {} = {}", si_a, si_b, add(si_a, si_b))
            }

    .. compliant_example::
        :id: compl_ex_BgUHiSB4kc4b
        :status: draft

        Saturation semantics means that instead of wrapping around or resulting in an error,
        any result that falls outside the valid range of the integer type is clamped:

        - To the maximum value, if the result were to be greater than the maximum value, or
        - To the minimum value, if the result were to be smaller than the minimum,

        Saturation semantics always conform to this rule because they ensure that integer operations do not result in arithmetic overflow. 
        This compliant solution shows how to use saturating functions to provide saturation semantics for some basic arithmetic operations.

        .. code-block:: rust

            fn add(a: i32, b: i32) -> i32 {
                a.saturating_add(b)
            }

            fn sub(a: i32, b: i32) -> i32 {
                a.saturating_sub(b)
            }

            fn mul(a: i32, b: i32) -> i32 {
                a.saturating_mul(b)
            }

    .. compliant_example::
        :id: compl_ex_BgUHiSB4kd4b
        :status: draft

        ``Saturating<T>`` is a wrapper type in Rust’s ``core`` library (``core::num::Saturating<T>``) that makes arithmetic operations on the wrapped value perform saturating arithmetic instead of wrapping, panicking, or overflowing.
        ``Saturating<T>`` is useful when you have a section of code or a data type where all arithmetic must be saturating.
        This compliant solution uses the ``Saturating<T>`` type to define several functions that perform basic integer operations using saturation semantics.

        .. code-block:: rust

            use std::num::Saturating;

            fn add(si_a: Saturating<i32>, si_b: Saturating<i32>) -> Saturating<i32> {
                si_a + si_b
            }

            fn sub(si_a: Saturating<i32>, si_b: Saturating<i32>) -> Saturating<i32> {
                si_a - si_b
            }

            fn mul(si_a: Saturating<i32>, si_b: Saturating<i32>) -> Saturating<i32> {
                si_a * si_b
            }

            fn main() {    
                let si_a = Saturating(i32::MAX);
                let si_b = Saturating(i32::MAX);
                println!("{} + {} = {}", si_a, si_b, add(si_a, si_b))
            }

    .. non_compliant_example::
        :id: non_compl_ex_cCh2RQUXeH0O
        :status: draft

        This noncompliant code example example prevents divide-by-zero errors, but does not prevent arithmetic overflow.

        .. code-block:: rust

            fn div(s_a: i64, s_b: i64) -> Result<i64, DivError> {
                if s_b == 0 {
                    Err(DivError::DivisionByZero)
                } else {
                    Ok(s_a / s_b)
                }
            }

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4d
        :status: draft

        This compliant solution eliminates the possibility of both divide-by-zero errors and arithmetic overflow:

        .. code-block:: rust


            fn div(s_a: i64, s_b: i64) -> Result<i64, DivError> {
                if s_b == 0 {
                    Err("division by zero")
                } else if s_a == i64::MIN && s_b == -1 {
                    Err("arithmetic overflow")
                } else {
                    Ok(s_a / s_b)
                }
            }

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

.. guideline:: Do not use an integer type as a divisor during integer division
   :id: gui_7y0GAMmtMhch
   :category: advisory
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: decidable
   :scope: module
   :tags: numerics, subset

   Do not provide a right operand of
   `integer type <https://rust-lang.github.io/fls/types-and-traits.html#integer-types>`_  
   during a `division expression
   <https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression>`_ or `remainder expression
   <https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression>`_ when the left operand also has integer type.

    This rule applies to the following primitive integer types:

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
      :id: rat_vLFlPWSCHRje
      :status: draft

      Integer division and integer remainder division both panic when the right operand has a value of zero.
      Division by zero is undefined in mathematics because it leads to contradictions and there is no consistent value that can be assigned as its result.

   .. non_compliant_example::
      :id: non_compl_ex_0XeioBrgfh5z
      :status: draft

      Both the division and remainder operations in this non-compliant example will panic if evaluated because the right operand is zero.

      .. code-block:: rust

         let x = 0;
         let y = 5 / x; // This line will panic.
         let z = 5 % x; // This line would also panic.

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXb
      :status: draft

      Checked division prevents division by zero from occurring.
      The programmer can then handle the returned :std:`std::option::Option`.
      Using checked division and remainder is particularly important in the signed integer case,
      where arithmetic overflow can also occur when dividing the minimum representable value by -1.

      .. code-block:: rust

         // Using the checked division API
         let y = match 5i32.checked_div(0) {
             None => 0
             Some(r) => r
         };

         // Using the checked remainder API
         let z = match 5i32.checked_rem(0) {
             None => 0
             Some(r) => r
         };

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXc
      :status: draft

      This compliant solution creates a divisor using :std:`std::num::NonZero`.
      :std:`std::num::NonZero` is a wrapper around primitive integer types that guarantees the contained value is never zero.
      :std:`std::num::NonZero::new` creates a new binding that represents a value that is known not to be zero.
      This ensures that functions operating on its value can correctly assume that they are not being given zero as their input. 

      Note that the test for arithmetic overflow that occurs when dividing the minimum representable value by -1 is unnecessary
      in this compliant example because the result of the division expression is an unsigned integer type.

      .. code-block:: rust

         let x = 0u32;
         if let Some(divisor) = match NonZero::<u32>::new(x) {
            let result = 5u32 / divisor;
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

   Integer division by zero results in a panic.
   This includes both `division expressions
   <https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression>`_ and `remainder expressions
   <https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression>`_.

   Division and remainder expressions on signed integers are also susceptible to arithmetic overflow.
   Overflow is covered in full by the guideline `Ensure that integer operations do not result in arithmetic overflow`.

   This rule applies to the following primitive integer types:

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

   This rule does not apply to evaluation of the :std:`core::ops::Div` trait on types other than `integer
   types <https://rust-lang.github.io/fls/types-and-traits.html#integer-types>`_.

   This rule is a less strict version of `Do not use an integer type as a divisor during integer division`.
   All code that complies with that rule also complies with this rule.

   .. rationale::
      :id: rat_h84NjY2tLSBW
      :status: draft

      Integer division by zero results in a panic; an abnormal program state that may terminate the process and must be avoided.

   .. non_compliant_example::
      :id: non_compl_ex_LLs3vY8aGz0F
      :status: draft

      This non-compliant example panics when the right operand is zero for either the division or remainder operations.

      .. code-block:: rust

         let x = 0;
         let y = 5 / x; // Results in a panic.
         let z = 5 % x; // Also results in a panic.

   .. compliant_example::
      :id: compl_ex_Ri9pP5Ch3kcc
      :status: draft

      Compliant examples from `Do not use an integer type as a divisor during integer division` are also valid for this rule.
      Additionally, the check for zero can be performed manually, as in this compliant example.
      However, as the complexity of the control flow leading to the invariant increases,
      it becomes increasingly harder for both programmers and static analysis tools to reason about it.

      Note that the test for arithmetic overflow is not necessary for unsigned integers.

      .. code-block:: rust

         // Checking for zero by hand
         let x = 0u32;
         let y = if x != 0u32 {
             5u32 / x
         } else {
             0u32
         };

         let z = if x != 0u32 {
             5u32 % x
         } else {
             0u32
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

.. guideline:: Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the operand
    :id: gui_RHvQj8BHlz9b 
    :category: advisory
    :status: draft
    :release: 1.7.0-latest
    :fls: fls_sru4wi5jomoe
    :decidability: decidable
    :scope: module
    :tags: numerics, reduce-human-error, maintainability, surprising-behavior, subset

    Shifting negative positions or a value greater than or equal to the width of the left operand
    in `shift left and shift right expressions <https://rust-lang.github.io/fls/expressions.html#bit-expressions>`_
    are defined by this guideline to be *out-of-range shifts*.
    The Rust FLS incorrectly describes this behavior as <`arithmetic overflow <https://github.com/rust-lang/fls/issues/632>`_.
    
    If the types of both operands are integer types,
    the shift left expression ``lhs << rhs`` evaluates to the value of the left operand ``lhs`` whose bits are 
    shifted left by the number of positions specified by the right operand ``rhs``.
    Vacated bits are filled with zeros. 
    The expression ``lhs << rhs`` evaluates to :math:`\mathrm{lhs} \times 2^{\mathrm{rhs}}`, 
    cast to the type of the left operand.
    If the value of the right operand is negative or greater than or equal to the width of the left operand,
    then the operation results in an out-of-range shift.

    If the types of both operands are integer types,
    the shift right expression ``lhs >> rhs`` evaluates to the value of the left operand ``lhs`` 
    whose bits are shifted right by the number of positions speicifed by the right operand ``rhs``.
    If the type of the left operand is any signed integer type and is negative,
    the vacated bits are filled with ones.
    Otherwise, vacated bits are filled with zeros.
    The expression ``lhs >> rhs`` evaluates to :math:`\mathrm{lhs} / 2^{\mathrm{rhs}}`,
    cast to the type of the left operand.
    If the value of the right operand is negative,
    greater than or equal to the width of the left operand,
    then the operation results in an out-of-range shift.

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

    Any type can support ``<<`` or ``>>`` if you implement the trait:

    .. code-block:: rust

       use core::ops::Shl;

       impl Shl<u32> for MyType {
           type Output = MyType;
           fn shl(self, rhs: u32) -> Self::Output { … }
       }

    You may choose any type for the right operand (not just integers), because you control the implementation.

    This rule is based on The CERT C Coding Standard Rule
   `INT34-C. Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the left operand <https://wiki.sei.cmu.edu/confluence/x/ItcxBQ>`_.

    .. rationale:: 
        :id: rat_3MpR8QfHodGT 
        :status: draft

        Avoid out-of-range shifts in shift left and shift right expressions.
        Shifting by a negative value, or by a value greater than or equal to the width of the left operand
        are non-sensical expressions which typically indicate a logic error has occured.

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcn 
        :status: draft

        This noncompliant example shifts by a negative value (-1) and also by greater than or equal to the number of bits that exist in the left operand (40):.

        .. code-block:: rust

            fn main() {
                let bits : u32 = 61;
                let shifts = vec![-1, 4, 40];

                for sh in shifts {
                    println!("{bits} << {sh} = {:?}", bits << sh);
                }
            }

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcn 
        :status: draft

        This noncompliant example test the value of ``sh`` to ensure the value of the right operand is negative or greater 
        than or equal to the width of the left operand.

        .. code-block:: rust

            fn main() {
                let bits: u32 = 61;
                let shifts = vec![-1, 0, 4, 40];

                for sh in shifts {
                    if sh >= 0 && sh < 32 {
                        println!("{bits} << {sh} = {}", bits << sh);
                    }
                 }
            }

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcm
        :status: draft

        The call to ``bits.wrapping_shl(sh)`` in this noncompliant example yields ``bits << mask(sh)``,
        where ``mask`` removes any high-order bits of ``sh`` that would cause the shift to exceed  the bitwidth of ``bits``.
        Note that this is not the same as a rotate-left.
        The ``wrapping_shl`` has the same behavior as the ``<<`` operator in release mode.

          .. code-block:: rust

             fn main() {
                 let bits : u32 = 61;
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     println!("{bits} << {sh} = {:?}", bits.wrapping_shl(sh));
                 }
             }

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcp
        :status: draft

        The call to ``bits.overflowing_shl(sh)`` in this noncompliant shifts ``bits`` left by ``sh`` bits.
        Returns a tuple of the shifted version of self along with a boolean indicating whether the shift value was larger than or equal to the number of bits.
        If the shift value is too large, then value is masked (N-1) where N is the number of bits, and this value is used to perform the shift.

          .. code-block:: rust

             fn main() {
                 let bits: u32 = 61;
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     let (result, overflowed) = bits.overflowing_shl(sh);
                     if overflowed {
                         println!("{bits} << {sh} shift too large");
                     } else {
                         println!("{bits} << {sh} = {result}");
                     }
                 }
             }

    .. compliant_example::
        :id: compl_ex_xpPQqYeEPGIo 
        :status: draft

        This compliant example performs left shifts via the `checked_shl <https://doc.rust-lang.org/core/index.html?search=%22checked_shl%22>`_
        function and right shifts via the `checked_shr <https://doc.rust-lang.org/core/index.html?search=%22checked_shr%22>`_ function.
        Both of these functions are defined in `core <https://doc.rust-lang.org/core/index.html>`_.

          ``<T>::checked_shl(M)`` returns a value of type ``Option<T>``:

          * If ``M < 0``\ , the output is ``None``
          * If ``0 <= M < N`` for ``T`` of size ``N`` bits, then the output is ``Some(T)``
          * If ``N <= M``\ , the output is ``None``

          Checked shift operations make programmer intent explicit and eliminates out-of-range shifts.
          Shifting by:

          * negative values is impossible because ``checked_shl`` only accepts unsigned integers as shift lengths, and
          * greater than or equal to the number of bits that exist in the left operand returns a ``None`` value.

          .. code-block:: rust

             fn main() {
                 let bits : u32 = 61;
                 // let shifts = vec![-1, 4, 40];
                 //                    ^--- Compiler rejects negative shifts
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     println!("{bits} << {sh} = {:?}", bits.checked_shl(sh));
                 }
             }

.. guideline:: Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the operand
    :id: gui_LvmzGKdsAgI5 
    :category: mandatory
    :status: draft
    :release: 1.0.0-latest
    :fls: fls_sru4wi5jomoe
    :decidability: undecidable
    :scope: module
    :tags: numerics, surprising-behavior, defect

    Shifting negative positions or a value greater than or equal to the width of the left operand
    in `shift left and shift right expressions <https://rust-lang.github.io/fls/expressions.html#bit-expressions>`_
    are defined by this guideline to be *out-of-range shifts*.
    The Rust FLS incorrectly describes this behavior as <`arithmetic overflow <https://github.com/rust-lang/fls/issues/632>`_.
    
    If the types of both operands are integer types,
    the shift left expression ``lhs << rhs`` evaluates to the value of the left operand ``lhs`` whose bits are 
    shifted left by the number of positions speicifed by the right operand ``rhs``.
    Vacated bits are filled with zeros. 
    The expression ``lhs << rhs`` evaluates to :math:`\mathrm{lhs} \times 2^{\mathrm{rhs}}`, 
    cast to the type of the left operand.
    If the value of the right operand is negative or greater than or equal to the width of the left operand,
    then the operation results in an out-of-range shift.

    If the types of both operands are integer types,
    the shift right expression ``lhs >> rhs`` evaluates to the value of the left operand ``lhs`` 
    whose bits are shifted right by the number of positions speicifed by the right operand ``rhs``.
    If the type of the left operand is any signed integer type and is negative,
    the vacated bits are filled with ones.
    Otherwise, vacated bits are filled with zeros.
    The expression ``lhs >> rhs`` evaluates to :math:`\mathrm{lhs} / 2^{\mathrm{rhs}}`,
    cast to the type of the left operand.
    If the value of the right operand is negative,
    greater than or equal to the width of the left operand,
    then the operation results in an out-of-range shift.

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

    Any type can support ``<<`` or ``>>`` if you implement the trait:

    .. code-block:: rust

       use core::ops::Shl;

       impl Shl<u32> for MyType {
           type Output = MyType;
           fn shl(self, rhs: u32) -> Self::Output { … }
       }

    You may choose any type for the right operand (not just integers), because you control the implementation.

   This rule is a less strict but undecidable version of 
   `Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the operand`.
   All code that complies with that rule also complies with this rule.

    This rule is based on The CERT C Coding Standard Rule
   `INT34-C. Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the left operand <https://wiki.sei.cmu.edu/confluence/x/ItcxBQ>`_.

    .. rationale:: 
        :id: rat_tVkDl6gOqz25 
        :status: draft

        Avoid out-of-range shifts in shift left and shift right expressions.
        Shifting by a negative value, or by a value greater than or equal to the width of the left operand
        are non-sensical expressions which typically indicate a logic error has occured.

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcn 
        :status: draft

        This noncompliant example shifts by a negative value (-1) and also by greater than or equal to the number of bits that exist in the left operand (40):.

        .. code-block:: rust

            fn main() {
                let bits : u32 = 61;
                let shifts = vec![-1, 4, 40];

                for sh in shifts {
                    println!("{bits} << {sh} = {:?}", bits << sh);
                }
            }

    .. compliant_example::
        :id: compl_ex_Ux1WqHbGKV73 
        :status: draft

        This compliant example test the value of ``sh`` to ensure the value of the right operand is negative or greater 
        than or equal to the width of the left operand.

        .. code-block:: rust

            fn main() {
                let bits: u32 = 61;
                let shifts = vec![-1, 0, 4, 40];

                for sh in shifts {
                    if sh >= 0 && sh < 32 {
                        println!("{bits} << {sh} = {}", bits << sh);
                    }
                 }
            }

    .. compliant_example::
        :id: compl_ex_Ux1WqHbGKV74
        :status: draft

        The call to ``bits.overflowing_shl(sh)`` in this noncompliant shifts ``bits`` left by ``sh`` bits.
        Returns a tuple of the shifted version of self along with a boolean indicating whether the shift value was larger than or equal to the number of bits.
        If the shift value is too large, then value is masked (N-1) where N is the number of bits, and this value is used to perform the shift.

          .. code-block:: rust

             fn safe_shl(bits: u32, shift: u32) -> u32 {
                 let (result, overflowed) = bits.overflowing_shl(shift);
                 if overflowed {
                     0
                 } else {
                     result
                 }
             }

             fn main() {
                 let bits: u32 = 61;
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     let result = safe_shl(bits, sh);
                     println!("{bits} << {sh} = {result}");
                 }
             }
