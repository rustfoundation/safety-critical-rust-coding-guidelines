.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not use an integer type as a divisor during integer division
   :id: gui_7y0GAMmtMhch
   :category: advisory
   :status: draft
   :release: latest
   :fls: fls_Q9dhNiICGIfr
   :decidability: decidable
   :scope: module
   :tags: numerics, subset

   Do not provide a right operand of integer type :cite:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
   during a division expression :cite:`gui_7y0GAMmtMhch:FLS-DIVISION-EXPR` or remainder expression :cite:`gui_7y0GAMmtMhch:FLS-REMAINDER-EXPR` when the left operand also has integer type.

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

      .. rust-example::
          :compile_fail:

          fn main() {
              let x = 0;
              let _y = 5 / x; // This line will panic.
              let _z = 5 % x; // This line would also panic.
          }

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXb
      :status: draft

      Checked division prevents division by zero from occurring.
      The programmer can then handle the returned :std:`std::option::Option`.
      Using checked division and remainder is particularly important in the signed integer case,
      where arithmetic overflow can also occur when dividing the minimum representable value by -1.

      .. rust-example::

         fn main() {
             // Using the checked division API
             let _y = match 5i32.checked_div(0) {
                 None => 0,
                 Some(r) => r,
             };

             // Using the checked remainder API
             let _z = match 5i32.checked_rem(0) {
                 None => 0,
                 Some(r) => r,
             };
         }

   .. compliant_example::
      :id: compl_ex_k1CD6xoZxhXc
      :status: draft

      This compliant solution creates a divisor using :std:`std::num::NonZero`.
      :std:`std::num::NonZero` is a wrapper around primitive integer types that guarantees the contained value is never zero.
      :std:`std::num::NonZero::new` creates a new binding that represents a value that is known not to be zero.
      This ensures that functions operating on its value can correctly assume that they are not being given zero as their input. 

      Note that the test for arithmetic overflow that occurs when dividing the minimum representable value by -1 is unnecessary
      in this compliant example because the result of the division expression is an unsigned integer type.

      .. rust-example::
         :version: 1.79

         use std::num::NonZero;

         fn main() {
             let x = 0u32;
             if let Some(divisor) = NonZero::<u32>::new(x) {
                 let _result = 5u32 / divisor;
             }
         }

   .. bibliography::
      :id: bib_7y0GAMmtMhch
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_7y0GAMmtMhch:FLS-INTEGER-TYPES`
           - The Rust FLS. "Types and Traits - Integer Types." https://rust-lang.github.io/fls/types-and-traits.html#integer-types
         * - :bibentry:`gui_7y0GAMmtMhch:FLS-DIVISION-EXPR`
           - The Rust FLS. "Expressions - Syntax - DivisionExpression." https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression
         * - :bibentry:`gui_7y0GAMmtMhch:FLS-REMAINDER-EXPR`
           - The Rust FLS. "Expressions - Syntax - RemainderExpression." https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression
