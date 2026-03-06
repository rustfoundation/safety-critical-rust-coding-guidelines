.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

When defensive error handling is weak, recoverable faults can propagate into unsafe or unchecked paths where required invariants are not re-established, allowing safe-callable flows to trigger Rust undefined behavior at run time.
=====================================================================================================================================================================================================================================

.. guideline:: When defensive error handling is weak, recoverable faults can propagate into unsafe or unchecked paths where required invariants are not re-established, allowing safe-callable flows to trigger Rust undefined behavior at run time.
    :id: gui_692a3c0abe93
    :category: advisory
    :status: draft
    :release: 1.85.1
    :fls: fls_Q9dhNiICGIfr
    :decidability: undecidable
    :scope: module
    :tags: unsafe, defect

    Error-handling logic in Rust, especially on paths that interact with unsafe code, shall preserve all safety invariants under fault conditions and shall not permit any safe caller to trigger undefined behavior. Defensive handling shall reject or stop execution when invariants cannot be proven (rather than continuing in a degraded state), and shall prevent known undefined-behavior classes including data races, dangling or misaligned access, pointer/projection bound violations, aliasing-rule violations, and mutation of immutable bytes. Weak defensive handling increases run-time risk by turning recoverable failures into unsound behavior that static compilation checks alone cannot prevent.

    .. rationale::
        :id: rat_gui692a3c0ab
        :status: draft

        Weak defensive error handling in Rust increases risk when failure paths can still reach unsafe operations without re-establishing safety preconditions. Rust’s phase distinction means successful compilation does not guarantee run-time safety for dynamic conditions; if error paths degrade into unchecked execution, safe callers may still trigger unsound unsafe behavior. The Rust Reference states that programs are incorrect if they exhibit undefined behavior (including in unsafe code), and unsafe code is only sound when safe clients cannot trigger such behavior. Therefore, weak handling of recoverable faults (e.g., continuing after invalid input/state) can convert ordinary errors into run-time undefined behavior classes such as out-of-bounds projection, dangling/misaligned access, aliasing violations, data races, or mutation of immutable bytes, with consequences ranging from crashes to silent corruption and non-deterministic system behavior.

    .. non_compliant_example::
        :id: non_compl_ex_gui692a3c0ab
        :status: draft

        Weak defensive error handling can turn a recoverable input problem into undefined behavior. In this example, parse failure and empty input are logged but execution continues into unchecked indexing. Because unchecked projection must still satisfy in-bounds requirements at run time, this pattern can produce UB (for example, out-of-bounds read), making the unsafe path unsound for safe callers and increasing the risk of crashes or silent corruption.

        .. rust-example::
           :miri: expect_ub

            fn parse_index(text: &str) -> Result<usize, ()> {
                text.parse::<usize>().map_err(|_| ())
            }

            fn read_value_weak(values: &[u32], idx_text: &str) -> u32 {
                let idx = match parse_index(idx_text) {
                    Ok(i) => i,
                    Err(_) => {
                        eprintln!("invalid index text; falling back to 0");
                        0
                    }
                };

                if values.is_empty() {
                    eprintln!("values is empty, but continuing anyway");
                }

                unsafe { *values.get_unchecked(idx) }
            }

            fn main() {
                let values: [u32; 0] = [];
                let _ = read_value_weak(&values, "not-a-number");
            }


    .. compliant_example::
        :id: compl_ex_gui692a3c0ab
        :status: draft

        Strong defensive handling rejects invalid states before any risky operation and keeps access on checked paths. Here, parse errors, empty slices, and out-of-range indices all return explicit errors, so execution does not continue in a degraded state. This preserves safety invariants under fault conditions and avoids UB-prone unchecked projection.

        .. rust-example::
           :miri:

            fn parse_index(text: &str) -> Result<usize, &'static str> {
                text.parse::<usize>().map_err(|_| "invalid index text")
            }

            fn read_value_checked(values: &[u32], idx_text: &str) -> Result<u32, &'static str> {
                let idx = parse_index(idx_text)?;

                if values.is_empty() {
                    return Err("values is empty");
                }

                values
                    .get(idx)
                    .copied()
                    .ok_or("index out of bounds")
            }

            fn main() {
                let values = [10_u32, 20, 30];

                assert_eq!(read_value_checked(&values, "1"), Ok(20));
                assert!(read_value_checked(&values, "not-a-number").is_err());
                assert!(read_value_checked(&values, "99").is_err());
            }


    .. bibliography::
        :id: bib_gui692a3c0ab
        :status: draft

        .. list-table::
           :header-rows: 0
           :widths: auto
           :class: bibliography-table

          * - :bibentry:`gui_692a3c0abe93:RUSTREF-BEHAVIOR-CONSIDERED-UNDEFINED-A9609319`
            - Reference. "The Rust Reference - Behavior Considered Undefined."
          * - :bibentry:`gui_692a3c0abe93:RUSTREF-CRATES-AND-SOURCE-FILES-3C862EE4`
            - Reference. "The Rust Reference - Crates and Source Files."
