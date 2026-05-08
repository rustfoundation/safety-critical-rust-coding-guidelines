.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

The 'as' operator should not be used with numeric operands
==========================================================

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

   **Exception:** ``as`` may be used with an integer type as the right operand and an expression of floating
   point type as the left operand.

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

      A pointer-to-address or address-to-pointer cast should be performed using the exposed or strict provenance APIs
      (``addr``, ``expose_provenance``, ``with_addr`` or ``with_exposed_provenance``).

      Casts between pointer types should use the ``cast``, ``cast_const`` or ``cast_mut`` methods to better
      communicate intent.

   .. non_compliant_example::
      :id: non_compl_ex_hzGUYoMnK59w
      :status: draft

      ``as`` used here can change the value range or lose precision.
      Even when it doesn't, nothing enforces the correct behaviour or communicates whether
      we intend to allow lossy conversions, or only expect valid conversions.

      .. rust-example::

         #[allow(dead_code)]
         fn f1(x: u16, y: i32, _z: u64, w: u8) {
           let _a = w as char;           // non-compliant
           let _b = y as u32;            // non-compliant - changes value range, converting negative values
           let _c = x as i64;            // non-compliant - could use .into()

           let d = y as f32;            // non-compliant - lossy
           let e = d as f64;            // non-compliant - could use .into()
           let _f = e as f32;            // non-compliant - lossy

           let _g = e as i64;            // non-compliant - lossy despite object size

           let b: u32 = 0;
           let p1: *const u32 = &b;
           let _a1 = p1 as usize;        // compliant by exception
           let _a2 = p1 as u16;          // non-compliant - may lose address range
           let _a3 = p1 as u64;          // non-compliant - use .addr() or .expose_provenance()

           let a1 = p1 as usize;
           let _p2 = a1 as *const u32;  // non-compliant
           let a2 = p1 as u16;
           let _p3 = a2 as *const u32;  // non-compliant (and most likely not in a valid address range)
         }
         #
         # fn main() {}

   .. compliant_example::
      :id: compl_ex_uilHTIOgxD37
      :status: draft

      Valid conversions that are guaranteed to preserve exact values can be communicated
      better with ``into()`` or ``from()``.
      Valid conversions that risk losing value, where doing so would be an error, can
      communicate this and include an error check, with ``try_into`` or ``try_from``.
      Other forms of conversion may find explicit functions better communicate their intent.

      .. rust-example::
         :miri:

         use std::convert::TryInto;

         #[allow(dead_code)]
         fn f2(x: u16, y: i32, _z: u64, w: u8) {
           let _a: char            = w.into();
           let _b: Result <u32, _> = y.try_into(); // produce an error on range clip
           let _c: i64             = x.into();

           let d = f32::from(x);  // u16 is within range, u32 is not
           let _e = f64::from(d);
           // let f = f32::from(e); // no From exists

           // let g = ...            // no From exists

           let h: u32 = 0;
           let p1: * const u32 = &h;
           let a1 = p1.expose_provenance();     // compliant
           let a2 = p1.addr();     // compliant, can't be turned back into a dereferencable pointer

           // does something entirely different,
           // reinterpreting the bits of z as the IEEE bit pattern of a double
           // precision object, rather than converting the integer value
           let _f1: f64 = _z.to_bits();
         }
         #
         # fn main() {}
