.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. guideline:: Use at least Rust Edition 2024
    :id: gui_ZDLZzjeOwLSU
    :category: required
    :status: draft
    :release: 1.85-latest
    :fls: fls_8kqo952gjhaf
    :decidability: decidable
    :scope: crate
    :tags: readability,reduce-human-error

    Use at least Rust Edition 2024 to enforce ``unsafe`` tokens must be made visible in all locations where the compiler is aware an ``unsafe`` obligation extends to the code.

    .. rationale::
        :id: rat_eQV3s9ggNegr
        :status: draft

        In Rust Edition 2024, several forms of code which involved explicit usage of ``unsafe`` tokens in new locations (attributes and ``extern`` blocks) were made mandatory. Due to backwards compatibility concerns, these did not previously require ``unsafe``. Some cases involving ``unsafe`` attributes were still linted against in some previous Rust versions by the ``unsafe_code`` lint, after it was discovered they had safety concerns, but due to backwards compatibility concerns they did not initially require use of a visible ``unsafe`` token. In Rust Edition 2024, however, it is both possible and required to use ``unsafe`` appropriately in these contexts.

    .. non_compliant_example::
        :id: non_compl_ex_FdmuPXGZr4EO
        :status: draft

        An ``extern`` block can cause UB if it is misdeclared. This applies even if the definitions are not called, as the wrong definition may still prevail, especially after linking is considered.

        .. rust-example::

            use std::ffi;

            // If another function by this name is in the compiled object's namespace,
            // Rust allows undefined behavior from the program linker or loader.
            // An `unsafe` token is not required in Rust 2021, though it is linted as such.
            #[no_mangle]
            fn something() {}

            extern "C" {
                // If malloc in the compiled object's namespace accepts a usize argument, 
                // the compiler may generate code for calls to this function using this definition,
                // thus the runtime behavior is undefined.
                fn malloc(size: f32) -> *mut ffi::c_void;
            }


    .. compliant_example::
        :id: compl_ex_wR1FEyLRKmrq
        :status: draft

        Using at least Rust Edition 2024 enforces that these things that involve safety obligations require the ``unsafe`` token.

        .. rust-example::

            use std::ffi;

            #[unsafe(no_mangle)]
            fn something() {}

            unsafe extern "C" {
                // Here the assumption is that malloc is the one defined by C's stdlib.h
                // and that size_of::<usize>() == size_of::<size_t>()
                fn malloc(size: usize) -> *mut ffi::c_void;
                fn free(ptr: *mut ffi::c_void);
            }
