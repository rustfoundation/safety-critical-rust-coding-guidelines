.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. guideline:: Assure visibility of ``unsafe`` tokens in unsafe code
    :id: gui_ZDLZzjeOwLSU
    :category: required
    :status: draft
    :release: 1.85-latest
    :fls: fls_8kqo952gjhaf
    :decidability: decidable
    :scope: crate
    :tags: readability, reduce-human-error

    Assure visibility of ``unsafe`` tokens in all locations where the compiler is aware an ``unsafe`` obligation extends to the code.

    In Rust Edition 2024 :cite:`gui_aB3cDe4fGh5i:RUST-EDITION-GUIDE`, several forms of code which involved explicit usage of ``unsafe`` tokens
    were made mandatory in attributes and ``extern`` blocks :cite:`gui_jK6lMn7oPq8r:RUST-REF-UNSAFE-KEYWORD`.
    Prior Rust editions did not require an ``unsafe`` in these locations.
    Some cases involving ``unsafe`` attributes were still linted against in some previous Rust versions by the ``unsafe_code`` lint
    :cite:`gui_sT9uVw0xYz1a:RUST-LINT-UNSAFE`,
    after it was discovered they had safety concerns,
    but due to backwards compatibility concerns they did not initially require use of a visible ``unsafe`` token.
    Starting with Rust Edition 2024, the use ``unsafe`` is required in these contexts.

    Rust 1.82  enabled use of ``unsafe`` around attributes: https://github.com/rust-lang/blog.rust-lang.org/blob/27e63bd0c2e68dd8b4eb06b67194cc4c2a9e84be/posts/2024-10-17-Rust-1.82.0.md#unsafe-attributes

    It also included unsafe extern on stable: https://github.com/rust-lang/blog.rust-lang.org/blob/main/content/Rust-1.82.0.md#safe-items-with-unsafe-extern

   Unfortunately, it seems we never started warning about ``unsafe_code`` for two attributes, oddly enough: ``link`` and ``link_ordinal``.

   I believe those attributes require themselves to be on ``extern "C"`` blocks, so they are implicitly covered by unsafe extern.

   Each of the attributes referenced by this issue must be explicitly marked unsafe as well as ``extern "C" {}`` blocks: rust-lang/rust#82499

    .. rationale::
        :id: rat_eQV3s9ggNegr
        :status: draft

        * Auditability and Review
          * ``unsafe`` blocks create clear audit boundaries where reviewers can focus attention on code that may
          violate safety guarantees :cite:`gui_bC2dEf3gHi4j:RUSTNOMICON-MEET-SAFE`
         * Safety-critical standards like ISO 26262 :cite:`gui_kL5mNo6pQr7s:ISO-26262` and DO-178C :cite:`gui_tU8vWx9yZa0b:DO-178C` require traceability of hazardous operations
         * Helps enumerate and document all places where safety requirements must be manually upheld

        * Explicit Acknowledgment of Responsibility

          * The ``unsafe`` keyword signals that the programmer is taking responsibility for upholding invariants the compiler cannot verify
          * Prevents accidental use of ``unsafe`` operations without conscious decision
          * Aligns with the principle of "defense in depth" in safety-critical systems

        * Visibility

          * Encouraging visibility discourages hiding unsafe operations inside safe-looking abstractions without proper encapsulation

        * Static Analysis and Tooling

          * Tools like ``cargo-geiger`` :cite:`gui_cD3eGh4iJk5l:CARGO-GEIGER`, ``unsafe-inspect``, and custom linters can automatically locate and count unsafe blocks
          * Enables metrics like "unsafe density" for safety assessments
          * Supports qualification evidence required by certification standards

        * Traceability for Certification

          * Safety-critical certifications require demonstrating that hazardous operations are identified and controlled
          * Visible ``unsafe`` tokens provide direct linkage to safety cases and hazard analyses
          * Facilitates the required documentation that each unsafe operation has been reviewed and justified

    .. non_compliant_example::
        :id: non_compl_ex_FdmuPXGZr4EO
        :status: draft

        An ``extern`` block can cause undefined behavior if it is misdeclared :cite:`gui_jK6lMn7oPq8r:RUST-REF-UNSAFE-KEYWORD`.
        This applies even if the definitions are not called, as the wrong definition may still prevail,
        especially after linking is considered.

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

            fn main() {
                // Call the no_mangle function
                something();

                // Call the extern function (requires unsafe block)
                unsafe {
                    let ptr = malloc(1024.0);
                    if !ptr.is_null() {
                        // In a real program, we'd use the allocated memory here
                        // and then free it with libc::free
                        println!("malloc returned: {:?}", ptr);
                    }
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
   .. bibliography::
      :id: bib_WNCi5njUWLuZ
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_aB3cDe4fGh5i:RUST-EDITION-GUIDE`
           - The Rust Edition Guide. "Rust 2024." https://doc.rust-lang.org/edition-guide/rust-2024/index.html.

         * - :bibentry:`gui_jK6lMn7oPq8r:RUST-REF-UNSAFE-KEYWORD`
           - The Rust Reference. "Unsafe Keyword." https://doc.rust-lang.org/reference/unsafe-keyword.html.

         * - :bibentry:`gui_sT9uVw0xYz1a:RUST-LINT-UNSAFE`
           - Rust Compiler Lint Documentation. "unsafe_code." https://doc.rust-lang.org/rustc/lints/listing/allowed-by-default.html#unsafe-code.

         * - :bibentry:`gui_bC2dEf3gHi4j:RUSTNOMICON-MEET-SAFE`
           - The Rustonomicon. "Meet Safe and Unsafe." https://doc.rust-lang.org/nomicon/meet-safe-and-unsafe.html.

         * - :bibentry:`gui_kL5mNo6pQr7s:ISO-26262`
           - International Organization for Standardization. "ISO 26262 - Road vehicles - Functional safety." https://www.iso.org/standard/68383.html.

         * - :bibentry:`gui_tU8vWx9yZa0b:DO-178C`
           - RTCA, Inc. "DO-178C: Software Considerations in Airborne Systems and Equipment Certification." https://store.accuristech.com/standards/rtca-do-178c.

         * - :bibentry:`gui_cD3eGh4iJk5l:CARGO-GEIGER`
           - cargo-geiger contributors. "cargo-geiger: Detects usage of unsafe Rust." https://github.com/geiger-rs/cargo-geiger.

         * - :bibentry:`gui_mN6oQp7rSt8u:RUST-REF-EXTERN`
           - The Rust Reference. "External blocks." https://doc.rust-lang.org/reference/items/external-blocks.html.

         * - :bibentry:`gui_vW9xYz0aAb1c:RUST-REF-UNSAFE-ATTR`
           - The Rust Reference. "Unsafe attributes." https://doc.rust-lang.org/reference/attributes.html#unsafe-attributes.

         * - :bibentry:`gui_dE2fGh3iJk4l:FERROCENE-SPEC`
           - Ferrocene GmbH. "Ferrocene Language Specification." https://spec.ferrocene.dev/.

         * - :bibentry:`gui_0cuTYG8RVYjg:RUST-REF-UNION`
           - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html.

         * - :bibentry:`gui_0cuTYG8RVYjg:UCG-VALIDITY`
           - Rust Unsafe Code Guidelines. "Validity and Safety Invariant." https://rust-lang.github.io/unsafe-code-guidelines/glossary.html#validity-and-safety-invariant.
