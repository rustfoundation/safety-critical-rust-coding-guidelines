.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Defensive error handling in Rust SHALL block fault or invalid states from reaching unsafe operations, so safe callers cannot trigger undefined behavior through degraded error paths.
=====================================================================================================================================================================================

.. guideline:: Defensive error handling in Rust SHALL block fault or invalid states from reaching unsafe operations, so safe callers cannot trigger undefined behavior through degraded error paths.
    :id: gui_692a3c0abe93
    :category: required
    :status: draft
    :release: 1.85.1-
    :fls: fls_vsk4vhnuiyyz
    :decidability: undecidable
    :scope: module
    :tags: unsafe, defect

    Defensive error handling in Rust SHALL prevent error states from reaching unsafe operations or safety-critical control paths. Unsafe code interfaces SHALL be designed so that safe callers cannot, through omitted checks or degraded error paths, trigger undefined behavior; this includes preventing conditions that can lead to data races. Because some safety effects manifest at run time rather than compile time, error paths SHALL preserve soundness invariants under all expected and fault conditions.

    .. rationale::
        :id: rat_gui692a3c0ab
        :status: draft

        Hazard: undefined behavior in a Rust program (explicitly including data races). Mechanism: when defensive error handling is weak, invalid or fault states are detected but not blocked before reaching unsafe operations; this breaks the requirement that unsafe code remain sound for safe callers, so safe-callable paths can still trigger undefined behavior. Consequence: because Rust semantics include run-time (dynamic) behavior in addition to compile-time checks, these unsound error paths can manifest as run-time memory-safety violations and nondeterministic failures, undermining safety-critical behavior even when compilation succeeds.

    .. non_compliant_example::
        :id: non_compl_ex_gui692a3c0ab
        :status: draft

        Weak defensive error handling can let invalid states flow into unsafe operations. In this example, the API is safe to call, but on an out-of-bounds index it records an error and still performs pointer arithmetic and a write. The code compiles (static checks pass), yet at run time the unsafe write can go out of bounds, making the unsafe abstraction unsound and potentially causing undefined behavior.

        .. rust-example::
           :miri: skip

            use std::ptr::NonNull;

            #[derive(Debug)]
            enum WriteError {
                OutOfBounds,
            }

            struct RawBuf {
                ptr: NonNull<u8>,
                len: usize,
            }

            impl RawBuf {
                fn from_vec(v: &mut Vec<u8>) -> Self {
                    let ptr = NonNull::new(v.as_mut_ptr()).expect("vector pointer must be non-null");
                    Self { ptr, len: v.len() }
                }

                // Non-compliant: safe API that fails to defend unsafe preconditions.
                fn write_byte(&mut self, index: usize, value: u8) -> Result<(), WriteError> {
                    let mut status = Ok(());
                    if index >= self.len {
                        status = Err(WriteError::OutOfBounds);
                    }

                    // BUG: still executes even when index is invalid.
                    unsafe {
                        *self.ptr.as_ptr().add(index) = value;
                    }

                    status
                }
            }

            fn main() {
                let mut v = vec![0u8; 4];
                let mut b = RawBuf::from_vec(&mut v);

                let _ = b.write_byte(999, 1); // out-of-bounds path still writes
            }


    .. compliant_example::
        :id: compl_ex_gui692a3c0ab
        :status: draft

        Defensive handling must prevent unsafe code from running when preconditions fail. This version makes validation explicit and returns early on error, so invalid indices never reach pointer arithmetic. The unsafe operation remains encapsulated behind checks, preserving a sound safe interface under run-time fault conditions.

        .. rust-example::
           :miri: skip

            use std::ptr::NonNull;

            #[derive(Debug)]
            enum WriteError {
                OutOfBounds,
            }

            struct RawBuf {
                ptr: NonNull<u8>,
                len: usize,
            }

            impl RawBuf {
                fn from_vec(v: &mut Vec<u8>) -> Self {
                    let ptr = NonNull::new(v.as_mut_ptr()).expect("vector pointer must be non-null");
                    Self { ptr, len: v.len() }
                }

                fn write_byte(&mut self, index: usize, value: u8) -> Result<(), WriteError> {
                    if index >= self.len {
                        return Err(WriteError::OutOfBounds);
                    }

                    unsafe {
                        // Preconditions established by checks above: index < len and ptr from live Vec.
                        *self.ptr.as_ptr().add(index) = value;
                    }
                    Ok(())
                }
            }

            fn main() {
                let mut v = vec![0u8; 4];
                let mut b = RawBuf::from_vec(&mut v);

                assert!(b.write_byte(2, 7).is_ok());
                assert!(b.write_byte(999, 1).is_err());
            }


    .. bibliography::
        :id: bib_gui692a3c0ab
        :status: draft

        .. list-table::
           :header-rows: 0
           :widths: auto
           :class: bibliography-table

          * - :bibentry:`gui_692a3c0abe93:RUSTREF-BEHAVIOR-UB-A9609319`
            - Rust Project Developers. "The Rust Reference: Behavior considered undefined." https://doc.rust-lang.org/reference/behavior-considered-undefined.html#behavior-considered-undefined
          * - :bibentry:`gui_692a3c0abe93:RUSTREF-PHASE-RUNTIME-3C862EE4`
            - Rust Project Developers. "The Rust Reference: Crates and source files." https://doc.rust-lang.org/reference/crates-and-source-files.html#crates-and-source-files
