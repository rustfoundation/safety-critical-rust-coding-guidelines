.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Types and Traits
================

.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Ensure reads of union fields produce valid values for the field's type
   :id: gui_UnionFieldValidity
   :category: required
   :status: draft
   :release: 1.85.0
   :fls: fls_oFIRXBPXu6Zv
   :decidability: undecidable
   :scope: system
   :tags: defect, safety, undefined-behavior

   When reading from a union field, ensure that the underlying bytes constitute a valid value 
   for that field's type.
   Reading a union field whose bytes do not represent a valid value 
   for the field's type is undefined behavior.

   Before accessing a union field:
   
   * Verify that the union was last written through that field, or
   * Verify that the union was written through a field whose bytes are valid when reinterpreted as the target field's type, or
   * Use explicit validity checks when the active field is uncertain

   .. rationale::
      :id: rat_UnionFieldValidityReason
      :status: draft

      Unions allow multiple fields to occupy the same memory, similar to C unions.
      Unlike enums, unions do not track which field is currently active. It is the programmer's
      responsibility to ensure that when a field is read, the underlying bytes are valid for
      that field's type [RUST-REF-UNION]_.

      Every type has a *validity invariant* — a set of constraints that all values of
      that type must satisfy [UCG-VALIDITY]_.
      Reading a union field performs a *typed read*,
      which asserts that the bytes are valid for the target type.
      Violating this invariant is undefined behavior.

      Examples of validity requirements for common types:

      * **bool**: Must be ``0`` (false) or ``1`` (true). Any other value (e.g., ``3``) is invalid.
      * **char**: Must be a valid Unicode scalar value (0x0 to 0xD7FF or 0xE000 to 0x10FFFF).
      * **References**: Must be non-null and properly aligned.
      * **Enums**: Must hold a valid discriminant value.
      * **Floating point**: All bit patterns are valid for the ``f32`` or ``f64``.type
      * **Integers**: All bit patterns are valid for integer types.

      Consequences of reading invalid values include:

      * Immediate undefined behavior, even if the value is not used
      * Miscompilation due to compiler assumptions about valid values
      * Security vulnerabilities from unexpected program behavior
      * Non-deterministic behavior that varies across optimization levels or platforms

   .. non_compliant_example::
      :id: non_compl_ex_UnionBool
      :status: draft

      This example reads a boolean from a union field containing an invalid bit pattern.
      The value ``3`` is not a valid boolean (only ``0`` and ``1`` are valid).

      .. code-block:: rust

         union IntOrBool {
             i: u8,
             b: bool,
         }

         fn main() {
             let u = IntOrBool { i: 3 };
             
             // Noncompliant: reading bool field with invalid value (3)
             let invalid_bool = unsafe { u.b };  // UB: 3 is not a valid bool
         }

   .. non_compliant_example::
      :id: non_compl_ex_UnionChar
      :status: draft

      This example reads a ``char`` from a union containing an invalid Unicode value.

      .. code-block:: rust

         union IntOrChar {
             i: u32,
             c: char,
         }

         fn main() {
             // 0xD800 is a surrogate, not a valid Unicode scalar value
             let u = IntOrChar { i: 0xD800 };
             
             // Non-compliant: reading char field with invalid Unicode value
             let invalid_char = unsafe { u.c };  // UB: surrogates are not valid chars
         }

   .. non_compliant_example::
      :id: non_compl_ex_UnionEnum
      :status: draft

      This example reads an enum from a ``union`` containing an invalid discriminant.

      .. code-block:: rust

         #[repr(u8)]
         enum Color {
             Red = 0,
             Green = 1,
             Blue = 2,
         }

         union IntOrColor {
             i: u8,
             c: Color,
         }

         fn main() {
             let u = IntOrColor { i: 42 };
             
             // Noncompliant: 42 is not a valid Color discriminant
             let invalid_color = unsafe { u.c };  // UB: no Color variant for 42
         }

   .. non_compliant_example::
      :id: non_compl_ex_UnionRef
      :status: draft

      This example reads a reference from a ``union`` containing a null or misaligned pointer.

      .. code-block:: rust

         union PtrOrRef {
             p: *const i32,
             r: &'static i32,
         }

         fn main() {
             let u = PtrOrRef { p: std::ptr::null() };
             
             // Non-compliant: null is not a valid reference
             let invalid_ref = unsafe { u.r };  // UB: references cannot be null
         }

   .. compliant_example::
      :id: compl_ex_UnionTrackField
      :status: draft

      Track the active field explicitly to ensure valid reads.

      .. code-block:: rust

         union IntOrBool {
             i: u8,
             b: bool,
         }

         enum ActiveField {
             Int,
             Bool,
         }

         struct SafeUnion {
             data: IntOrBool,
             active: ActiveField,
         }

         impl SafeUnion {
             fn new_int(value: u8) -> Self {
                 Self {
                     data: IntOrBool { i: value },
                     active: ActiveField::Int,
                 }
             }

             fn new_bool(value: bool) -> Self {
                 Self {
                     data: IntOrBool { b: value },
                     active: ActiveField::Bool,
                 }
             }

             fn get_bool(&self) -> Option<bool> {
                 match self.active {
                     // Compliant: only read bool when we know it was written as bool
                     ActiveField::Bool => Some(unsafe { self.data.b }),
                     ActiveField::Int => None,
                 }
             }
         }

   .. compliant_example::
      :id: compl_ex_UnionSameField
      :status: draft

      Read from the same field that was written.

      .. code-block:: rust

         union IntOrBool {
             i: u8,
             b: bool,
         }

         fn main() {
             let u = IntOrBool { b: true };
             
             // Compliant: reading the same field that was written
             let valid_bool = unsafe { u.b };
             println!("bool value: {}", valid_bool);
         }

   .. compliant_example::
      :id: compl_ex_UnionValidReinterpret
      :status: draft

      Reinterpret between types where all bit patterns are valid.

      .. code-block:: rust

         union IntBytes {
             i: u32,
             bytes: [u8; 4],
         }

         fn main() {
             let u = IntBytes { i: 0x12345678 };
             
             // Compliant: all bit patterns are valid for [u8; 4]
             let bytes = unsafe { u.bytes };
             println!("bytes: {:?}", bytes);
             
             let u2 = IntBytes { bytes: [0x11, 0x22, 0x33, 0x44] };
             
             // Compliant: all bit patterns are valid for u32
             let int_value = unsafe { u2.i };
             println!("integer: 0x{:08X}", int_value);
         }

   .. compliant_example::
      :id: compl_ex_UnionValidateBool
      :status: draft

      Validate bytes before reading as a constrained type.

      .. code-block:: rust

         union IntOrBool {
             i: u8,
             b: bool,
         }

         fn try_read_bool(u: &IntOrBool) -> Option<bool> {
             // Read as integer first (always valid for u8)
             let raw = unsafe { u.i };
             
             // Validate before interpreting as bool
             match raw {
                 0 => Some(false),
                 1 => Some(true),
                 _ => None,  // Invalid bool value
             }
         }

         fn main() {
             let u1 = IntOrBool { i: 1 };
             let u2 = IntOrBool { i: 3 };
             
             // Compliant: validates before reading as bool
             println!("u1 as bool: {:?}", try_read_bool(&u1));  // Some(true)
             println!("u2 as bool: {:?}", try_read_bool(&u2));  // None
         }

   .. bibliography::
      :id: bib_UnionFieldValidity
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: 10 80

         * - .. [RUST-REF-UNION]
           - The Rust Project Developers. "Rust Reference: Unions." *The Rust Reference*, n.d. https://doc.rust-lang.org/reference/items/unions.html.
         * - .. [UCG-VALIDITY]
           - Rust Unsafe Code Guidelines Working Group. "Validity and Safety Invariant." *Rust Unsafe Code Guidelines*, n.d. https://rust-lang.github.io/unsafe-code-guidelines/glossary.html#validity-and-safety-invariant.

.. guideline:: Use strong types to differentiate between logically distinct values
   :id: gui_xztNdXA2oFNC
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
      :id: rat_kYiIiW8R2qD2
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
      :id: non_compl_ex_PO5TyFsRTlWw
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
            let d = 100;
            let t = = 10;
            let _result = travel(t, d);  // Compiles, but semantically incorrect
         }

   .. non_compliant_example::
      :id: non_compl_ex_PO5TyFsRTlWv
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
      :id: compl_ex_WTe7GoPu5Ez1
      :status: draft

      This compliant example uses newtypes to create distinct types for ``Meters``, ``Seconds``, and ``MetersPerSecond``.
      The compiler enforces correct usage, preventing accidental swapping of parameters.
      The function signature clearly conveys the intended semantics of each parameter and return value.  

       .. code-block:: rust

         use std::ops::Div;

         #[derive(Debug, Clone, Copy)]
         struct Meters(u32);

         #[derive(Debug, Clone, Copy)]
         struct Seconds(u32);

         #[derive(Debug, Clone, Copy)]
         struct MetersPerSecond(u32);

         impl Div<Seconds> for Meters {
             type Output = MetersPerSecond;

             fn div(self, rhs: Seconds) -> Self::Output {
                  MetersPerSecond(self.0 / rhs.0)
             }
          }

          fn main() {
              let d = Meters(100);
              let t = Seconds(10);
              let result = d / t;  // Clean and type-safe!
              println!("{:?}", result);  // MetersPerSecond(10)
          }
