.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

An integer shall not be converted to a pointer
==============================================

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

      .. rust-example::
        :miri:

        #[allow(dead_code)]
        fn f1(x: u16, y: i32, z: u64, w: usize) {
          let _p1 = x as * const u32;  // not compliant
          let _p2 = y as * const u32;  // not compliant
          let _p3 = z as * const u32;  // not compliant
          let _p4 = w as * const u32;  // not compliant despite being the right size

          let _f: f64 = 10.0;
          // let p5 = f as * const u32;  // not valid

          unsafe {
            // let p5: * const u32 = std::mem::transmute(x);  // not valid
            // let p6: * const u32 = std::mem::transmute(y);  // not valid

            #[allow(integer_to_ptr_transmutes)]
            let _p7: * const u32 = std::mem::transmute(z); // not compliant
            #[allow(integer_to_ptr_transmutes)]
            let _p8: * const u32 = std::mem::transmute(w); // not compliant

            let _p9: * const u32 = std::mem::transmute(_f); // not compliant, and very strange
          }
        }
        #
        # fn main() {}

   .. compliant_example::
      :id: compl_ex_oneKuF52yzrx
      :status: draft

      There is no compliant example of this operation.
