.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Ensure that integer operations do not result in arithmetic overflow
    :id: gui_dCquvqE1csI3
    :category: required
    :status: draft
    :release: 1.0 - latest
    :fls: fls_oFIRXBPXu6Zv
    :decidability: decidable
    :scope: system
    :tags: security, performance, numerics

    Eliminate `arithmetic overflow <https://rust-lang.github.io/fls/expressions.html#arithmetic-overflow>`__ of both signed and unsigned integer types. 
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

        .. rust-example::

            #[allow(dead_code)]
            fn add(si_a: i32, si_b: i32) {
              let _sum: i32 = si_a + si_b;
              // ...
            }
            #
            # fn main() {}

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

        .. rust-example::

            # #[derive(Debug)]
            #[allow(dead_code)]
            enum ArithmeticError { Overflow, DivisionByZero }
            use std::i32::{MAX as INT_MAX, MIN as INT_MIN};

            #[allow(dead_code)]
            fn add(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                if (si_b > 0 && si_a > INT_MAX - si_b)
                    || (si_b < 0 && si_a < INT_MIN - si_b)
                {
                    Err(ArithmeticError::Overflow)
                } else {
                    Ok(si_a + si_b)
                }
            }

            #[allow(dead_code)]
            fn sub(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                if (si_b < 0 && si_a > INT_MAX + si_b)
                    || (si_b > 0 && si_a < INT_MIN + si_b)
                {
                    Err(ArithmeticError::Overflow)
                } else {
                    Ok(si_a - si_b)
                }
            }

            #[allow(dead_code)]
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
            #
            # fn main() {}

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4c
        :status: draft

        This compliant example uses safe checked addition instead of manual bounds checks.
        Checked functions can reduce readability when complex arithmetic expressions are needed.

        .. rust-example::

            # #[derive(Debug)]
            #[allow(dead_code)]
            enum ArithmeticError { Overflow, DivisionByZero }

            #[allow(dead_code)]
            fn add(si_a: i32, si_b: i32) -> Result<i32, ArithmeticError> {
                si_a.checked_add(si_b).ok_or(ArithmeticError::Overflow)
            }

            #[allow(dead_code)]
            fn sub(a: i32, b: i32) -> Result<i32, ArithmeticError> {
                a.checked_sub(b).ok_or(ArithmeticError::Overflow)
            }

            #[allow(dead_code)]
            fn mul(a: i32, b: i32) -> Result<i32, ArithmeticError> {
                a.checked_mul(b).ok_or(ArithmeticError::Overflow)
            }
            #
            # fn main() {}

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4b
        :status: draft

        Wrapping behavior must be explicitly requested. This compliant example uses wrapping functions.

        .. rust-example::

            #[allow(dead_code)]
            fn add(a: i32, b: i32) -> i32 {
                a.wrapping_add(b)
            }

            #[allow(dead_code)]
            fn sub(a: i32, b: i32) -> i32 {
                a.wrapping_sub(b)
            }

            #[allow(dead_code)]
            fn mul(a: i32, b: i32) -> i32 {
                a.wrapping_mul(b)
            }
            #
            # fn main() {}

    .. compliant_example::
        :id: compl_ex_BhUHiRB4kc4b
        :status: draft

        Wrapping behavior call also be achieved using the ``Wrapping<T>`` type as in this compliant solution.
        The ``Wrapping<T>`` type is a ``struct`` found in the ``std::num`` module that explicitly enables two's complement
        wrapping arithmetic for the inner type ``T`` (which must be an integer or ``usize/isize``). 
        The ``Wrapping<T>`` type provides a consistent way to force wrapping behavior in all build modes,
        which is useful in specific scenarios like implementing cryptography or hash functions where wrapping arithmetic is the intended behavior.

        .. rust-example::

            use std::num::Wrapping;

            fn add(si_a: Wrapping<i32>, si_b: Wrapping<i32>) -> Wrapping<i32> {
                si_a + si_b
            }

            #[allow(dead_code)]
            fn sub(si_a: Wrapping<i32>, si_b: Wrapping<i32>) -> Wrapping<i32> {
                si_a - si_b
            }

            #[allow(dead_code)]
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

        .. rust-example::

            #[allow(dead_code)]
            fn add(a: i32, b: i32) -> i32 {
                a.saturating_add(b)
            }

            #[allow(dead_code)]
            fn sub(a: i32, b: i32) -> i32 {
                a.saturating_sub(b)
            }

            #[allow(dead_code)]
            fn mul(a: i32, b: i32) -> i32 {
                a.saturating_mul(b)
            }
            #
            # fn main() {}

    .. compliant_example::
        :id: compl_ex_BgUHiSB4kd4b
        :status: draft

        ``Saturating<T>`` is a wrapper type in Rust's ``core`` library (``core::num::Saturating<T>``) that makes arithmetic operations on the wrapped value perform saturating arithmetic instead of wrapping, panicking, or overflowing.
        ``Saturating<T>`` is useful when you have a section of code or a data type where all arithmetic must be saturating.
        This compliant solution uses the ``Saturating<T>`` type to define several functions that perform basic integer operations using saturation semantics.

        .. rust-example::

            use std::num::Saturating;

            fn add(si_a: Saturating<i32>, si_b: Saturating<i32>) -> Saturating<i32> {
                si_a + si_b
            }

            #[allow(dead_code)]
            fn sub(si_a: Saturating<i32>, si_b: Saturating<i32>) -> Saturating<i32> {
                si_a - si_b
            }

            #[allow(dead_code)]
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

        .. rust-example::

            # #[derive(Debug)]
            #[allow(dead_code)]
            enum DivError { DivisionByZero, Overflow }

            #[allow(dead_code)]
            fn div(s_a: i64, s_b: i64) -> Result<i64, DivError> {
                if s_b == 0 {
                    Err(DivError::DivisionByZero)
                } else {
                    Ok(s_a / s_b)
                }
            }
            #
            # fn main() {}

    .. compliant_example::
        :id: compl_ex_BgUHiRB4kc4d
        :status: draft

        This compliant solution eliminates the possibility of both divide-by-zero errors and arithmetic overflow:

        .. rust-example::

            # #[derive(Debug)]
            #[allow(dead_code)]
            enum DivError { DivisionByZero, Overflow }

            #[allow(dead_code)]
            fn div(s_a: i64, s_b: i64) -> Result<i64, DivError> {
                if s_b == 0 {
                    Err(DivError::DivisionByZero)
                } else if s_a == i64::MIN && s_b == -1 {
                    Err(DivError::Overflow)
                } else {
                    Ok(s_a / s_b)
                }
            }
            #
            # fn main() {}
