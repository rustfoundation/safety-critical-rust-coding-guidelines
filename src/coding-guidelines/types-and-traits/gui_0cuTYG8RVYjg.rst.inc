.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: Ensure reads of union fields produce valid values for the field's type
   :id: gui_0cuTYG8RVYjg
   :category: required
   :status: draft
   :release: unknown
   :fls: fls_oFIRXBPXu6Zv
   :decidability: undecidable
   :scope: system
   :tags: defect, safety, undefined-behavior

   Ensure that the underlying bytes constitute a valid value for that field's type when reading from a union field.
   Reading a union field whose bytes do not represent a valid value for the field's type is undefined behavior.

   Before accessing a union field, verify that that the union was either:
   
   * last written through that field, or
   * written through a field whose bytes are valid when reinterpreted as the target field's type

   If the active field is uncertain, use explicit validity checks.

   .. rationale::
      :id: rat_8QeimyAvM7cH
      :status: draft

      Similar to C, unions allow multiple fields to occupy the same memory.
      Unlike enumeration types, unions do not track which field is currently active.
      You must ensure that when a field is read that
      the underlying bytes are valid for that field's type :cite:`gui_0cuTYG8RVYjg:RUST-REF-UNION`.

      Every type has a *validity invariant* — a set of constraints that all values of
      that type must satisfy :cite:`gui_0cuTYG8RVYjg:UCG-VALIDITY`.
      Reading a union field performs a *typed read*,
      which asserts that the bytes are valid for the target type.

      Examples of validity requirements for common types:

      * **bool**: Must be ``0`` (false) or ``1`` (true). Any other value (e.g., ``3``) is invalid.
      * **char**: Must be a valid Unicode scalar value (``0x0`` to ``0xD7FF`` or ``0xE000`` to ``0x10FFFF``).
      * **References**: Must be non-null and properly aligned.
      * **Enums**: Must hold a valid discriminant value.
      * **Floating point**: All bit patterns are valid for the ``f32`` or ``f64`` types.
      * **Integers**: All bit patterns are valid for integer types.

      Reading an invalid value is undefined behavior.

   .. non_compliant_example::
      :id: non_compl_ex_ecHYRXb4Ncpu
      :status: draft

      This noncompliant example reads an invalid bit pattern from a Boolean union field.
      The value ``3`` is not a valid value of type ``bool`` (only ``0`` and ``1`` are valid).

      .. rust-example::

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
      :id: non_compl_ex_8bloNOcsLEKX
      :status: draft

      This noncompliant example reads an invalid Unicode value from a ``union`` field of type ``char`` .

      .. rust-example::

         union IntOrChar {
             i: u32,
             c: char,
         }

         fn main() {
             // '0xD800' is a surrogate and not a valid Unicode scalar value
             let u = IntOrChar { i: 0xD800 };
             
             // Reading an invalid Unicode value from a union field of type 'char'
             unsafe { u.c };  // Noncompliant
         }

   .. non_compliant_example::
      :id: non_compl_ex_PsJAB4WglRZl
      :status: draft

      This noncompliant example reads an invalid discriminant from a union field of 'Color' enumeration type.

      .. rust-example::

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
      :id: non_compl_ex_aEx4HnDD8xIp
      :status: draft

      This noncompliant example reads a reference from a union containing a null pointer.
      A similar problem occurs when reading a misaligned pointer.

      .. rust-example::

         union PtrOrRef {
             p: *const i32,
             r: &'static i32,
         }

         fn main() {
             let u = PtrOrRef { p: std::ptr::null() };
             
             //  Undefined behavior reading a null value from a reference field of a union
             unsafe { u.r };  // Noncompliant
         }

   .. compliant_example::
      :id: compl_ex_x27meeLDMZNI
      :status: draft

      This compliant example tracks the active field explicitly to ensure valid reads.

      .. rust-example::

         #[repr(C)]
         #[derive(Copy, Clone)]
         union IntOrBoolData {
             i: u8,
             b: bool,
         }
         
         /// Tracks which field of the union is currently active.
         #[derive(Clone, Copy, PartialEq, Eq)]
         enum ActiveField {
             Int,
             Bool,
         }
         
         /// A union wrapper that tracks the active field at runtime.
         pub struct IntOrBool {
             data: IntOrBoolData,
             active: ActiveField,
         }
         
         impl IntOrBool {
             pub fn from_int(value: u8) -> Self {
                 Self {
                     data: IntOrBoolData { i: value },
                     active: ActiveField::Int,
                 }
             }
         
             pub fn from_bool(value: bool) -> Self {
                 Self {
                     data: IntOrBoolData { b: value },
                     active: ActiveField::Bool,
                 }
             }
         
             pub fn set_int(&mut self, value: u8) {
                 self.data.i = value;
                 self.active = ActiveField::Int;
             }
         
             pub fn set_bool(&mut self, value: bool) {
                 self.data.b = value;
                 self.active = ActiveField::Bool;
             }
         
             /// Returns the integer value if that field is active.
             pub fn as_int(&self) -> Option<u8> {
                 match self.active {
                     // SAFETY: We only read `i` when we know it was last written as `i`
                     ActiveField::Int => Some(unsafe { self.data.i }), // compliant
                     ActiveField::Bool => None,
                 }
             }
         
             /// Returns the boolean value if that field is active.
             pub fn as_bool(&self) -> Option<bool> {
                 match self.active {
                     // SAFETY: We only read `b` when we know it was last written as `b`
                     ActiveField::Bool => Some(unsafe { self.data.b }), // compliant
                     ActiveField::Int => None,
                 }
             }
         }
         
         fn main() {
             let mut value = IntOrBool::from_bool(true);
             assert_eq!(value.as_bool(), Some(true));
             assert_eq!(value.as_int(), None);
         
             value.set_int(42);
             assert_eq!(value.as_bool(), None);
             assert_eq!(value.as_int(), Some(42));
         }

   .. compliant_example::
      :id: compl_ex_Y7xaYuD2xdmq
      :status: draft

      This compliant example reads from the same field that was written.

      .. rust-example::

         #[repr(C)]
         #[derive(Copy, Clone)]
         union IntBytes {
             i: u32,
             bytes: [u8; 4],
         }
         
         fn get_int() -> u32 {
             let u = IntBytes { i: 0x12345678 };
         
             // SAFETY: All bit patterns are valid for [u8; 4]
             // Note: byte order depends on target endianness
             assert_eq!(unsafe { u.bytes }, 0x12345678_u32.to_ne_bytes()); // compliant
         
             let u2 = IntBytes {
                 bytes: [0x11, 0x22, 0x33, 0x44],
             };
         
             // SAFETY: All bit patterns are valid for 'u32'
             assert_eq!(unsafe { u2.i }, u32::from_ne_bytes([0x11, 0x22, 0x33, 0x44])); // compliant
             
             unsafe { u2.i } // compliant
         }

         fn main() {
            println!("{}", get_int());
         }   

   .. compliant_example::
      :id: compl_ex_Jsxenev7lNf0
      :status: draft

      This compliant example reinterprets the value as a different type where all bit patterns are valid.

      .. rust-example::

         #[repr(C)]
         #[derive(Copy, Clone)]
         union IntBytes {
             i: u32,
             bytes: [u8; 4],
         }

        fn get_bytes() -> [u8; 4] {
             let u = IntBytes { i: 0x12345678 };
         
             // SAFETY: All bit patterns are valid for '[u8; 4]'
             // Note: byte order depends on target endianness
             assert_eq!(unsafe { u.bytes }, 0x12345678_u32.to_ne_bytes()); // compliant
             unsafe { u.bytes }  // compliant
         }

         fn get_u32() -> u32 {         
             let u = IntBytes {
                 bytes: [0x11, 0x22, 0x33, 0x44],
             };
         
             // SAFETY: All bit patterns are valid for 'u32'
             assert_eq!(unsafe { u.i }, u32::from_ne_bytes([0x11, 0x22, 0x33, 0x44])); // compliant
             unsafe { u.i }  // compliant
         }

         fn main() {
             println!("{:#04x?}", get_bytes());
             println!("{}", get_u32());
         }

   .. compliant_example::
      :id: compl_ex_vIITtPAeKHrp
      :status: draft

      This compliant example validates bytes before reading as a constrained type.

      .. rust-example::

         #[repr(C)]
         union IntOrBool {
             i: u8,
             b: bool,
         }

         fn try_read_bool(u: &IntOrBool) -> Option<bool> {
             // SAFETY: Reading as `u8` is always valid because all bit patterns
             // are valid for `u8`, regardless of which field was last written.
             let raw = unsafe { u.i }; // compliant
         
             // Validate before interpreting as `bool` (only 0 and 1 are valid)
             match raw {
                 0 => Some(false),
                 1 => Some(true),
                 _ => None,
             } // compliant
         }

         fn main() {
             let u1 = IntOrBool { i: 1 };
             let u2 = IntOrBool { i: 3 };
         
             assert_eq!(try_read_bool(&u1), Some(true));
             assert_eq!(try_read_bool(&u2), None);
         }

   .. bibliography::
      :id: bib_WNCi5njUWLuZ
      :status: draft

      .. list-table::
         :header-rows: 0
         :widths: auto
         :class: bibliography-table

         * - :bibentry:`gui_0cuTYG8RVYjg:RUST-REF-UNION`
           - The Rust Reference. "Unions." https://doc.rust-lang.org/reference/items/unions.html.

         * - :bibentry:`gui_0cuTYG8RVYjg:UCG-VALIDITY`
           - Rust Unsafe Code Guidelines. "Validity and Safety Invariant." https://rust-lang.github.io/unsafe-code-guidelines/glossary.html#validity-and-safety-invariant.

