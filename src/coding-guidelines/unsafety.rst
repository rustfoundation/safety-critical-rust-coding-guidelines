.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Unsafety
========

.. guideline:: All unsafe code shall be contained inside a sound safe abstraction
    :id: gui_goekLVFUAjSM 
    :category: required
    :status: draft
    :release: -
    :fls: fls_jep7p27kaqlp
    :decidability: undecidable
    :scope: module
    :tags: undefined-behavior

    A safe abstraction is considered sound, when it is impossible to build a **safe** program using
    the safe abstraction that invokes undefined behavior.

    Safe abstractions shall be kept as small as possible and only include features that cannot be built
    on top in safe Rust.

    .. rationale:: 
        :id: rat_3FoizIv2mZ4Z 
        :status: draft

        Unsound safe abstractions leak the possibility for undefined behavior to safe Rust.
        With violations of this rule, it would no longer suffice to only focus on unsafe modules
        as the root cause of undefined behavior

        Because safe abstractions are more difficult to review compared to safe code due to the
        subtle semantics of unsafe operations, their size need to be minimized.

    .. non_compliant_example::
        :id: non_compl_ex_4Rj4YQkr1Nr4 
        :status: draft

        The following module with a safe API uses unsafe code and is therefore a safe abstraction.
        However, when passing a data slice with an index that is outside the range of the slice,
        the safe function will cause undefined behavior.

        .. code-block:: rust

            pub mod bad {
                pub fn get_value(data: &[i32], index: usize) -> i32 {
                    unsafe {
                        data.get_unchecked(usize)
                    }
                }
            }

    .. compliant_example::
        :id: compl_ex_aM7w7UbgSdvT 
        :status: draft

        This safe module checks that its argument are valid, (i.e., they satisfy the safety
        precondition of the unsafe operation) before performing the unsafe operation.

        .. code-block:: rust

            pub mod good {
                pub fn get_value(data: &[i32], index: usize) -> i32 {
                    assert!(usize < data.len());
                    unsafe {
                        data.get_unchecked(usize)
                    }
                }
            }
