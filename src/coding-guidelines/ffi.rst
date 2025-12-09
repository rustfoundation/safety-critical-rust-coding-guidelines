.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

FFI
===


.. guideline:: Use matching type declarations at the language boundary
    :id: gui_QmEmKMYSuQSl 
    :category: required
    :status: draft
    :release: 1.0.0-latest
    :fls: fls_v24ino4hix3m
    :decidability: decidable
    :scope: crate
    :tags: undefined-behavior,reduce-human-error

    If it is required or advisable (e.g. to provide a "rusty" interface) to use different types on the Rust side than on the foreign function side, the respective type changes shall not be done on the FFI boundary but on an additional layer above the FFI level.

    .. rationale:: 
        :id: rat_LnIHMWRaC19F 
        :status: draft

        If the languages on the FFI boundary do not agree on the type or its layout, size and alignment properties, undefined behavior might be invoked. It is therefore critical to reduce the possibility of such misalignment to an absolute minimum. Developers and/or tools shall therefore follow a set of strict rules that govern how a foreign type definition shall be translated to Rust.

        Since the only ubiquitously supported foreign calling ABI is the calling ABI of the C programming language, this rule will state how C types are to be translated. For any other language or ABI, it is required to document the respective translation rules.

        It is recommended that tooling is used to automate the generation of matching declarations where possible. If this is not possible (e.g. due to the pre-existence of code), it is recommended to set up tooling that is able to check the consistency of the type declarations.

    .. non_compliant_example::
        :id: non_compl_ex_9uNGhTr1I20O 
        :status: draft

        The example shows the import of a single function from C which populates a given out parameter with data about a file. Looking at both type definitions of the second parameter, we can see that types are used which might or might not match, depending on the used platform triple and the definition of size_t. While the resulting program might run perfectly well on your favorite 64 bit host platform, other platforms like a 16 bit embedded platform will most likely fail.

        .. code-block:: rust

            /* C side */
              typedef struct __file_info {
                  size_t size;
                  int epoch_time;
              } file_info;

              int get_name_size(const char* path, file_info* info_out) { ... }
              ```

              ```rust
              // Rust side
              use std::ffi;

              #[repr(C)]
              struct FileInfo {
                  size: i64,
                  epoch_time: i32,
              }

              unsafe extern "C" {
                  fn get_name_size(path: *const ffi::c_char, file_info: *mut FileInfo) -> std::ffi::c_int;
              }

    .. compliant_example::
        :id: compl_ex_TPV54bWJEmft 
        :status: draft

        By picking matching types for the Rust ``extern`` declaration, we ensure the usage of a type that is understood in the same way on both the Rust and the C side. The type to choose is unambiguous - for each type on C side, it is exactly specified which basic type or compound type to use on Rust side.

        .. code-block:: rust

            /* C side */
              typedef struct __file_info {
                  size_t size;
                  int epoch_time;
              } file_info;

              int get_name_size(const char* path, file_info* info_out) { ... }
              ```

              ```rust
              // Rust side
              use std::ffi;

              #[repr(C)]
              struct FileInfo {
                  size: libc::size_t,
                  epoch_time: std::ffi::c_int,
              }

              unsafe extern "C" {
                  fn get_name_size(path: *const ffi::c_char, file_info: *mut FileInfo) -> std::ffi::c_int;
              }
