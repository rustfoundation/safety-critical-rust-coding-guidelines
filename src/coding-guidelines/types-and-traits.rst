.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Types and Traits
================

.. guideline:: Use strong types to differentiate between logically distinct values
   :id: gui_xztNdXA2oFNB
   :category: advisory
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_cokwseo3nnr
   :decidability: undecidable
   :scope: module
   :tags: types, safety, understandability

   Parameters and variables with logically distinct types must be statically distinguishable by the type system.

   Use a newtype (e.g., ``struct Meters(u32);``) when:
   
   * Two or more quantities share the same underlying primitive representation but are logically distinct
   * Confusing them would constitute a semantic error
   * You need to improve type safety and encapsulation
   * You need to enable trait-based behavior
   * You need to establish new invariants
   
   .. rationale::
      :id: rat_kYiIiW8R2qD1
      :status: draft

      This rule ensures that parameters and variables convey intent directly through the type system to avoid accidental misuse of values with identical primitives but different semantics.
      In particular:
      * Prevents mixing logically distinct values.
        Primitive types like ``u32`` or ``u64`` can represent lengths, counters, timestamps, durations, IDs, or other values.
        Different semantic domains can be confused, leading to incorrect computations.
        The Rust type system prevents such mistakes when semantics are encoded into distinct types.
      * Improves static safety.
        Statically distinct types allow the compiler to enforce domain distinctions.
        Accidental swapping of parameters or returning the wrong quantity becomes a compile-time error.
      * Improves readability and discoverability.
        Intent-revealing names (``Meters``, ``Seconds``, ``UserId``) make code self-documenting.
        Type signatures become easier to read and understand.
      * Enables domain-specific trait implementations.
        Statically distinct types allow you to implement ``Add``, ``Mul``, or custom traits in ways that match the domain logic.
        Aliases cannot do this, because they are not distinct types.
      * Supports API evolution.
        Statically distinct types act as strong API contracts that can evolve independently from their underlying representations.

   .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWv
      :status: draft

      This noncompliant example uses primitive types directly, leading to potential confusion between ``distance`` and ``time``.
      Nothing prevents the caller from passing ``time`` as ``distance`` or vice-versa.
      The units of each type are not clear from the function signature alone.
      Mistakes compile cleanly and silently produce wrong results.

       .. code-block:: rust

         fn travel(distance: u32, time: u32) -> u32 {
            distance / time
         }

         fn main() {
            let d: Meters = 100;
            let t: Seconds = 10;
            let _result = travel(t, d);  // Compiles, but semantically incorrect
         }

      .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWu
      :status: draft

      This noncompliant example uses aliases instead of distinct types.
      Aliases do not create new types, so the compiler cannot enforce distinctions between ``Meters`` and ``Seconds``.
     
      Aliases cannot do this, because they are not distinct types.
      This noncompliant example uses primitive types directly, leading to potential confusion between ``distance`` and ``time``.
      Nothing prevents the caller from passing ``time`` as ``distance`` or vice-versa.
      The units of each type are not clear from the function signature alone.
      Mistakes compile cleanly and silently produce wrong results.

       .. code-block:: rust

         type Meters = u32;
         type Seconds = u32;
         type MetersPerSecond = u32;

         fn travel(distance: Meters, time: Seconds) -> MetersPerSecond {
            distance / time
         }

         fn main() {
            let d: Meters = 100;
            let t: Seconds = 10;
            let _result = travel(t, d);  // Compiles, but semantically incorrect
         }

   .. compliant_example::
      :id: compl_ex_WTe7GoPu5Ez0
      :status: draft

      This compliant example uses newtypes to create distinct types for ``Meters``, ``Seconds``, and ``MetersPerSecond``.
      The compiler enforces correct usage, preventing accidental swapping of parameters.
      The function signature clearly conveys the intended semantics of each parameter and return value.  

       .. code-block:: rust

         struct Meters(u32);
         struct Seconds(u32);
         struct MetersPerSecond(u32);

         fn travel(distance: Meters, time: Seconds) -> MetersPerSecond {
            MetersPerSecond(distance.0 / time.0)
         }

         fn main() {
            let d = Meters(100);
            let t = Seconds(10);
            let _result = travel(d, t);  // Correct usage
         }
