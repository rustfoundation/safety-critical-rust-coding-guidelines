.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Types and Traits
================

.. guideline:: Avoid Implicit Integer Wrapping
   :id: gui_xztNdXA2oFNB
   :category: required
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_cokwseo3nnr
   :decidability: decidable
   :scope: module
   :tags: numerics

   Code must not rely on Rust's implicit integer wrapping behavior that may occur in release
   builds. Instead, explicitly handle potential overflows using the standard library's checked, 
   saturating, or wrapping operations.

   .. rationale::
      :id: rat_kYiIiW8R2qD1
      :status: draft

      In debug builds, Rust performs runtime checks for integer overflow and will panic if detected.
      However, in release builds (with optimizations enabled), unless the flag `overflow-checks`_ is
      turned on, integer operations silently wrap around on overflow, creating potential for silent
      failures and security vulnerabilities. Note that overflow-checks only brings the default panic
      behavior from debug into release builds, avoiding potential silent wrap arounds. Nonetheless,
      abrupt program termination is usually not suitable and, therefore, turning this flag on must
      not be used as a substitute of explicit handling. Furthermore, the behavior in release mode is
      under consideration by the The Rust Language Design Team and in the future overflow checking
      may be turned on by default in release builds (it is a `frequently requested change`_).

      .. _overflow-checks: https://github.com/rust-lang/rust/blob/master/src/doc/rustc/src/codegen-options/index.md#overflow-checks
      .. _frequently requested change: https://lang-team.rust-lang.org/frequently-requested-changes.html#numeric-overflow-checking-should-be-on-by-default-even-in-release-mode
      
      Safety-critical software requires consistent and predictable behavior across all build
      configurations. Explicit handling of potential overflow conditions improves code clarity,
      maintainability, and reduces the risk of numerical errors in production.

   .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWv
      :status: draft
   
       .. code-block:: rust
   
         fn calculate_next_position(current: u32, velocity: u32) -> u32 {
             // Potential for silent overflow in release builds
             current + velocity
         }

   .. compliant_example::
      :id: compl_ex_WTe7GoPu5Ez0
      :status: draft
   
       .. code-block:: rust
   
         fn calculate_next_position(current: u32, velocity: u32) -> u32 {
             // Explicitly handle potential overflow with checked addition
             current.checked_add(velocity).expect("Position calculation overflowed")
         }

