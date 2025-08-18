.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Unsafety
========

.. guideline:: Undefined behavior shall not occur during the execution of a program
    :id: gui_n4sX2E4G2qoX 
    :category: required
    :status: draft
    :release: -
    :fls: fls_ovn9czwnwxue
    :decidability: undecidable
    :scope: system
    :tags: undefined-behavior

    This rule addresses all instances of undefined behavior not already covered by other guidelines.

    .. rationale:: 
        :id: rat_xYF9mDPQRStx 
        :status: draft

        Once an execution encounters undefined behavior it is impossible to reason about it anymore.
        Instances of undefined behavior can manifest in any kind of undesired behavior like
        crashes or silent memory corruption.

    .. non_compliant_example::
        :id: non_compl_ex_bkYi0Sb97r3N 
        :status: draft

        Explanation of code example.

        The only allowed representation of ``bool`` is either 0 or 1.
        Therefore, transmuting ``3_u8`` to ``bool`` violates its validity invariant and is undefined behavior.

        .. code-block:: rust

            fn example_function() {
                unsafe {
                    std::transmute<bool>(3_u8)
                }
            }

        A necessary condition to read the value behind a pointer is that it points to a live allocation.
        This is never the case for the live pointer, therefore reading a null pointer is undefined behavior.
        See the safety precondition of :std:`std::ptr::read`.

        .. code-block:: rust

            fn example_function() {
                unsafe {
                    std::ptr::read(std::ptr::null());
                }
            }


