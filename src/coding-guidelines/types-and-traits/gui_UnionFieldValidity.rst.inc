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

   When reading from a union field, ensure that the underlying bytes constitute a valid value for that field's type.
   Reading a union field whose bytes do not represent a valid value for the field's type is undefined behavior.

   Before accessing a union field:
   
   * Verify that the union was last written through that field, or
   * Verify that the union was written through a field whose bytes are valid when reinterpreted as the target field's type, or
   * Use explicit validity checks when the active field is uncertain

   .. rationale::
      :id: rat_UnionFieldValidityReason
      :status: draft

      Unions allow multiple fields to occupy the same memory, similar to C unions.
      Unlike enumeration types, unions do not track which field is currently active.
      You must ensure that when a field is read,
      the underlying bytes are valid for that field's type [UNION]_.

      Every type has a *validity invariant* — a set of constraints that all values of
      that type must satisfy [VALID]_.
      Reading a union field performs a *typed read*,
      which asserts that the bytes are valid for the target type.

      Examples of validity requirements for common types:

      * **bool**: Must be ``0`` (false) or ``1`` (true). Any other value (e.g., ``3``) is invalid.
      * **char**: Must be a valid Unicode scalar value (0x0 to 0xD7FF or 0xE000 to 0x10FFFF).
      * **References**: Must be non-null and properly aligned.
      * **Enums**: Must hold a valid discriminant value.
      * **Floating point**: All bit patterns are valid for the ``f32`` or ``f64``.type
      * **Integers**: All bit patterns are valid for integer types.

      Reading an invalid value is undefined behavior.

   .. non_compliant_example::
      :id: non_compl_ex_UnionBool
      :status: draft

      This noncompliant example reads a Boolean from a union field containing an invalid bit pattern.
      The value ``3`` is not a valid Boolean (only ``0`` and ``1`` are valid).

      .. code-block:: rust

         union IntOrBool {
             i: u8,
             b: bool,
         }

         fn main() {
             let u = IntOrBool { i: 3 };
             
             // Undefined behavior reading an invalid value from a union field of type 'bool'
             unsafe { u.b };  // Noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_UnionChar
      :status: draft

      This noncompliant example reads a ``char`` from a ``union`` containing an invalid Unicode value.

      .. code-block:: rust

         union IntOrChar {
             i: u32,
             c: char,
         }

         fn main() {
             // 0xD800 is a surrogate and not a valid Unicode scalar value
             let u = IntOrChar { i: 0xD800 };
             
             // Noncompliant: reading an invalid Unicode value from a union field of type 'char'
             unsafe { u.c };  // Noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_UnionEnum
      :status: draft

      This noncompliant example reads an invalid discriminant from a ``union`` field of 'Color' enumeration type.

      .. code-block:: rust

         #[repr(u8)]
         #[derive(Copy, Clone)]
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
             
             // Undefined behavior reading an invalid discriminant from the 'Color' enumeration type
             unsafe { u.c };  // Noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_UnionRef
      :status: draft

      This noncompliant example reads a reference from a ``union`` containing a null or misaligned pointer.

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

      This compliant example tracks the active field explicitly to ensure valid reads.

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

         fn main() {
             let union_bool = SafeUnion::new_bool(true);
             let union_int = SafeUnion::new_int(42);
             
             println!("Bool union as bool: {:?}", union_bool.get_bool());  // Some(true)
             println!("Int union as bool: {:?}", union_int.get_bool());    // None
         }

   .. compliant_example::
      :id: compl_ex_UnionSameField
      :status: draft

      This compliant solution read from the same field that was written.

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

      This compliant example reinterprets the value as a different types where all bit patterns are valid.

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

      This compliant solution validates bytes before reading as a constrained type.

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
         :widths: 5 60

         * - .. [UNION]
           - The Rust Project Developers. "Rust Reference: Unions." *The Rust Reference*, n.d. https://doc.rust-lang.org/reference/items/unions.html.
         * - .. [VALID]
           - Rust Unsafe Code Guidelines Working Group. "Validity and Safety Invariant." *Rust Unsafe Code Guidelines*, n.d. https://rust-lang.github.io/unsafe-code-guidelines/glossary.html#validity-and-safety-invariant.

>>>>>>> c93b2cb (Update types-and-traits.rst):src/coding-guidelines/types-and-traits.rst