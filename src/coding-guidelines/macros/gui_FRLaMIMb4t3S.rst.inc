.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. guideline:: Do not hide unsafe code in macros
    :id: gui_yQC2tSE2Qeii
    :category: advisory
    :status: draft
    :release: unclear-latest
    :fls: fls_4vjbkm4ceymk
    :decidability: decidable
    :scope: module
    :tags: safety, reduce-human-error

    Do not hide unsafe code in macro definitions.
    Macros that expand to unsafe code should preserve the ``unsafe`` token visibility.

    .. rationale::
        :id: rat_s7ffMlPUFt77
        :status: draft

        Macros that generate unsafe code obscure safety-critical code, making the code more difficult to review and audit.

    .. non_compliant_example::
        :id: non_compl_ex_YNX7AnWENTu7
        :status: draft

        Macros that generate unsafe code without preserving the ``unsafe`` token visibility obscure safety-critical code.
        This noncompliant example defines a ``deref_ptr`` macro that performs an unsafe pointer deference. 

        .. rust-example::

            // This macro hides the unsafe token from callers - noncompliant
            macro_rules! deref_ptr {
                ($ptr:expr) => {
                    unsafe { *$ptr }
                };
            }

            fn main() {
                let x = 42;
                let ptr = &x as *const i32;
                // The unsafe operation is hidden from the caller
                println!("val = {}", deref_ptr!(ptr));
            }


    .. compliant_example::
        :id: compl_ex_nBkfzueTWvTA
        :status: draft

        This compliant example requires the caller to wrap the macro invocation in an ``unsafe`` block,
        making the use of unsafe code obvious at the call site.
        Visibility can be further improved by prefixing the identifier for each unsafe macro with the string “unsafe\_”

        .. rust-example::

            // This macro requires the caller to acknowledge the unsafe operation - compliant
            macro_rules! unsafe_deref_ptr {
                ($ptr:expr) => {
                    *$ptr
                };
            }

            fn main() {
                let x = 42;
                let ptr = &x as *const i32;
                // The unsafe operation is visible at the call site
                let val = unsafe { unsafe_deref_ptr!(ptr) };
                println!("val = {}", val);
            }
