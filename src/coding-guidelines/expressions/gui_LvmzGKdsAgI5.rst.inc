.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Avoid out-or-range shifts
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
    shifted left by the number of positions specified by the right operand ``rhs``.
    Vacated bits are filled with zeros. 
    The expression ``lhs << rhs`` evaluates to :math:`\mathrm{lhs} \times 2^{\mathrm{rhs}}`, 
    cast to the type of the left operand.
    If the value of the right operand is negative or greater than or equal to the width of the left operand,
    then the operation results in an out-of-range shift.

    If the types of both operands are integer types,
    the shift right expression ``lhs >> rhs`` evaluates to the value of the left operand ``lhs`` 
    whose bits are shifted right by the number of positions specified by the right operand ``rhs``.
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

    .. rust-example::

       use core::ops::Shl;
       #[allow(dead_code)]
       struct MyType;

       impl Shl<u32> for MyType {
           type Output = MyType;
           fn shl(self, _rhs: u32) -> Self::Output { MyType }
       }
       #
       # fn main() {}

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
        are non-sensical expressions which typically indicate a logic error has occurred.

    .. non_compliant_example::
        :id: non_compl_ex_KLiDMsCesLx7 
        :status: draft

        This noncompliant example shifts by a negative value (-1) and also by greater than or equal to the number of bits that exist in the left operand (40):.

        .. rust-example::

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

        .. rust-example::

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

          .. rust-example::

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
