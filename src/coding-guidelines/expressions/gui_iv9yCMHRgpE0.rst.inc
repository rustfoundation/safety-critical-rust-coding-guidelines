.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

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

      .. rust-example::

        #[allow(dead_code)]
        fn f1(flag: u32, ptr: * const u32) {
          /* ... */
          let mut rep = ptr as usize;
          rep = (rep & 0x7fffff) | ((flag as usize) << 23);
          let _p2 = rep as * const u32;
        }
        #
        # fn main() {}

   .. compliant_example::
      :id: compl_ex_oBoluiKSvREu
      :status: draft

      This compliant solution uses a struct to provide storage for both the pointer and the flag value.
      This solution is portable to machines of different word sizes, both smaller and larger than 32 bits,
      working even when pointers cannot be represented in any integer type.

      .. rust-example::

        #[allow(dead_code)]
        struct PtrFlag {
          pointer: * const u32,
          flag: u32
        }

        #[allow(dead_code)]
        fn f2(flag: u32, ptr: * const u32) {
          let _ptrflag = PtrFlag {
            pointer: ptr,
            flag: flag
          };
          /* ... */
        }
        #
        # fn main() {}
