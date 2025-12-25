.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Do not shift an expression by a negative number of bits or by greater than or equal to the bitwidth of the operand
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
    The Rust FLS incorrectly describes this behavior as <`arithmetic overflow <https://github.com/rust-lang/fls/issues/632>`__.
    
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

    This rule is based on The CERT C Coding Standard Rule
    `INT34-C. Do not shift an expression by a negative number of bits or by greater than or equal to the number of bits that exist in the left operand <https://wiki.sei.cmu.edu/confluence/x/ItcxBQ>`_.

    .. rationale:: 
        :id: rat_3MpR8QfHodGT 
        :status: draft

        Avoid out-of-range shifts in shift left and shift right expressions.
        Shifting by a negative value, or by a value greater than or equal to the width of the left operand
        are non-sensical expressions which typically indicate a logic error has occurred.

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcn 
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

    .. non_compliant_example::
        :id: non_compl_ex_mvkgTL3kulZ5 
        :status: draft

        This noncompliant example test the value of ``sh`` to ensure the value of the right operand is negative or greater 
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

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcm
        :status: draft

        The call to ``bits.wrapping_shl(sh)`` in this noncompliant example yields ``bits << mask(sh)``,
        where ``mask`` removes any high-order bits of ``sh`` that would cause the shift to exceed  the bitwidth of ``bits``.
        Note that this is not the same as a rotate-left.
        The ``wrapping_shl`` has the same behavior as the ``<<`` operator in release mode.

          .. rust-example::

             fn main() {
                 let bits : u32 = 61;
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     println!("{bits} << {sh} = {:?}", bits.wrapping_shl(sh));
                 }
             }

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcx
        :status: draft

        This noncompliant example uses ``bits.unbounded_shr(sh)``.
        If ``sh`` is larger or equal to the width of ``bits``,
        the entire value is shifted out,
        which yields 0 for a positive number,
        and -1 for a negative number.
        The use of this function is noncompliant because it does not detect out-of-range shifts.

          .. rust-example::
              :version: 1.87

             fn main() {
                 let bits : u32 = 61;
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     println!("{bits} << {sh} = {:?}", bits.unbounded_shr(sh));
                 }
             }

    .. non_compliant_example::
        :id: non_compl_ex_O9FZuazu3Lcp
        :status: draft

        The call to ``bits.overflowing_shl(sh)`` in this noncompliant shifts ``bits`` left by ``sh`` bits.
        Returns a tuple of the shifted version of self along with a boolean indicating whether the shift value was larger than or equal to the number of bits.
        If the shift value is too large, then value is masked (N-1) where N is the number of bits, and this value is used to perform the shift.

          .. rust-example::

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

          .. rust-example::

             fn main() {
                 let bits : u32 = 61;
                 // let shifts = vec![-1, 4, 40];
                 //                    ^--- Compiler rejects negative shifts
                 let shifts = vec![4, 40];

                 for sh in shifts {
                     println!("{bits} << {sh} = {:?}", bits.checked_shl(sh));
                 }
             }
