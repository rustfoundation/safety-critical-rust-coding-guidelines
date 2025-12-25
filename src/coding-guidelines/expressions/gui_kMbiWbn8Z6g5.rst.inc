.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

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
   This includes both division expressions :cite:`gui_kMbiWbn8Z6g5:FLS-DIVISION-EXPR` and remainder expressions :cite:`gui_kMbiWbn8Z6g5:FLS-REMAINDER-EXPR`.

   Division and remainder expressions on signed integers are also susceptible to arithmetic overflow.
   Overflow is covered in full by the guideline `Ensure that integer operations do not result in arithmetic overflow`.

   This rule applies to the following primitive integer types :cite:`gui_kMbiWbn8Z6g5:FLS-INTEGER-TYPES`:

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

   This rule does not apply to evaluation of the :std:`core::ops::Div` trait on types other than integer types :cite:`gui_kMbiWbn8Z6g5:FLS-INTEGER-TYPES`.

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

      .. rust-example::
          :compile_fail:

          fn main() {
              let x = 0;
              let _y = 5 / x; // Results in a panic.
              let _z = 5 % x; // Also results in a panic.
          }

   .. compliant_example::
      :id: compl_ex_Ri9pP5Ch3kcc
      :status: draft

      Compliant examples from `Do not use an integer type as a divisor during integer division` are also valid for this rule.
      Additionally, the check for zero can be performed manually, as in this compliant example.
      However, as the complexity of the control flow leading to the invariant increases,
      it becomes increasingly harder for both programmers and static analysis tools to reason about it.

      Note that the test for arithmetic overflow is not necessary for unsigned integers.

      .. rust-example::

         fn main() {
             // Checking for zero by hand
             let x = 0u32;
             let _y = if x != 0u32 {
                 5u32 / x
             } else {
                 0u32
             };

             let _z = if x != 0u32 {
                 5u32 % x
             } else {
                 0u32
             };
         }

   .. bibliography::
      :id: bib_kMbiWbn8Z6g5
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_kMbiWbn8Z6g5:FLS-INTEGER-TYPES`
           - The Rust FLS. "Types and Traits - Integer Types." https://rust-lang.github.io/fls/types-and-traits.html#integer-types
         * - :bibentry:`gui_kMbiWbn8Z6g5:FLS-DIVISION-EXPR`
           - The Rust FLS. "Expressions - Syntax - DivisionExpression." https://rust-lang.github.io/fls/expressions.html#syntax_divisionexpression
         * - :bibentry:`gui_kMbiWbn8Z6g5:FLS-REMAINDER-EXPR`
           - The Rust FLS. "Expressions - Syntax - RemainderExpression." https://rust-lang.github.io/fls/expressions.html#syntax_remainderexpression
