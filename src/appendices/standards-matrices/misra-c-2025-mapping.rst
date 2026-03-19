Rust Cross Reference with MISRA C 2025
=======================================

The following tables provide a cross reference between the MISRA C 2025 guidelines and their applicability to Rust. The
first table covers guidelines that are applicable to Rust in general, while the second table covers additional
guidelines that are applicable in the presence of unsafe code. The third table lists guidelines that are not applicable
to Rust.

The origin of this assessment can be found at `MISRA C:2025 Addendum 6`_.


Table 1 – Guidelines applicable to Rust in general (safe Rust, no unsafe code present)
--------------------------------------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Guideline
     - Rationale
     - Safety critical Rust rule
     - Comment
   * - **Directives**
     -
     -
     -
   * - D.1.1
     - IDB
     - 
     -
   * - D.1.2
     - IDB
     -
     - intended to apply to experimental and unstable features, forcing full documentation
   * - D.2.1
     - UB, CQ, DC
     -
     -
   * - D.3.1
     - CQ
     -
     -
   * - D.4.1
     - UB, CQ
     -
     - often in the form of panics
   * - D.4.4
     - DC
     -
     - conditional compilation is provided by the cfg attribute
   * - D.4.5
     - DC
     -
     - "ambiguity" is determined by the project
   * - D.4.7
     - DC
     -
     - prefer Option, Result, etc. over in-band error values
   * - D.4.9
     - DC, CQ
     -
     -
   * - D.4.11
     - UB, IDB
     -
     -
   * - D.4.12
     - UB, CQ
     -
     -
   * - D.4.13
     - UB, DC
     -
     - many Rust APIs use the type system to enforce ordering
   * - D.4.14
     - UB, CQ
     -
     -
   * - D.4.15
     - UB, IDB, DC
     -
     - Rust implements IEEE-754
   * - D.5.2
     - UB
     -
     -
   * - D.5.3
     - UB, DC
     -
     -
   * - **Rules**
     -
     -
     -
   * - R.1.3
     - UB, IDB
     -
     -
   * - R.1.5
     - UB, IDB, DC
     -
     - this applies to deprecated APIs
   * - R.2.1
     - DC
     -
     -
   * - R.2.2
     - DC
     -
     -
   * - R.2.3
     - DC
     -
     -
   * - R.2.5
     - DC
     -
     -
   * - R.2.6
     - DC
     -
     -
   * - R.2.7
     - DC
     -
     -
   * - R.2.8
     - DC
     -
     -
   * - R.3.1
     - DC
     -
     - nested comments are fully supported
   * - R.5.2
     - UB, IDB, CQ
     -
     - no character limit, but one can be applied; has name spaces
   * - R.5.3
     - DC
     - :need:`gui_SJMrWDYZ0dN4`
     - this also applies to macro names
   * - R.5.6
     - DC
     -
     - the proper module system makes surprise name conflicts much less likely
   * - R.5.8
     - DC
     -
     - the proper module system makes surprise name conflicts much less likely
   * - R.5.9
     - DC
     -
     -
   * - R.7.1
     - DC
     -
     - Rust octals have a distinct prefix from decimals
   * - R.7.2
     - DC
     -
     - this is an error by default but can be enabled. Note that suffixes also make the size explicit
   * - R.8.7
     - DC
     -
     - items should not be declared pub if referenced in only one module
   * - R.8.9
     - DC
     -
     -
   * - R.8.13
     - DC
     -
     - ``mut`` should be avoided unless necessary
   * - R.9.1
     - UB
     -
     - enforced by rustc but can be bypassed by unsafe
   * - R.9.4
     - DC
     -
     - enforced by rustc
   * - R.11.3
     - UB
     -
     -
   * - R.11.4
     - UB, IDB
     - :need:`gui_PM8Vpf7lZ51U`
     -
   * - R.11.11
     - DC
     -
     - enforced by rustc
   * - R.12.1
     - DC
     -
     -
   * - R.13.1
     - UB
     -
     - order of evaluation is strict in Rust
   * - R.13.5
     - DC
     -
     -
   * - R.14.3
     - DC
     -
     -
   * - R.14.4
     - DC
     -
     - enforced by rustc
   * - R.15.4
     - DC
     -
     -
   * - R.15.5
     - DC
     -
     -
   * - R.15.7
     - DC
     -
     -
   * - R.17.2
     - UB, DC
     - :need:`gui_ot2Zt3dd6of1`
     -
   * - R.17.7
     - DC
     -
     - ``must_use`` can help indicate where this is important, but does not affect applicability
   * - R.17.8
     - DC
     -
     - this cannot be done accidentally without declaring parameters ``mut``
   * - R.17.11
     - DC
     -
     - a non-returning function can be declared to return a value type
   * - R.18.3
     - UB
     -
     -
   * - R.18.5
     - DC
     -
     -
   * - R.19.2
     - UB, DC
     - :need:`gui_0cuTYG8RVYjg`
     -
   * - R.19.3
     - UB
     -
     -
   * - R.21.25
     - UB
     -
     -
   * - R.22.13
     - UB, DC
     -
     -
   * - R.22.18
     - UB
     -
     -
   * - R.22.19
     - UB
     -
     -


Table 2 – Guidelines applicable to Rust in the presence of unsafe code
-----------------------------------------------------------------------

In addition to the rules from Table 1, these are the additional guidelines that need to be covered:

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Guideline
     - Rationale
     - Safety critical Rust rule
     - Comment
   * - **Directives**
     -
     -
     -
   * - D.4.2
     - IDB, CQ
     -
     -
   * - D.4.3
     - DC, CQ
     -
     -
   * - D.5.1
     - UB
     -
     - not all safe Rust types are race-free
   * - **Rules**
     -
     -
     -
   * - R.1.1
     - UB, IDB
     -
     -
   * - R.5.1
     - UB, IDB, DC
     -
     - no character limit, except in extern "C", but one can be set by project
   * - R.5.5
     - UB, IDB, DC
     -
     - macros and functions use different syntax
   * - R.5.10
     - UB, DC
     -
     - only possible in some cases. Previously Rule 21.2
   * - R.8.3
     - UB, DC
     -
     - an extern declaration shall have a type compatible with the C declaration
   * - R.8.5
     - DC
     -
     - may affect extern "C" declarations
   * - R.8.6
     - UB
     -
     - may affect extern "C" declarations
   * - R.8.15
     - UB
     -
     - may affect extern "C" declarations
   * - R.8.17
     - DC
     -
     - alignment applies to types, not objects
   * - R.9.7
     - UB
     -
     -
   * - R.10.5
     - DC
     - :need:`gui_ADHABsmK9FXz`
     - includes both safe ``as`` and unsafe ``transmute`` operations
   * - R.10.8
     - DC
     - :need:`gui_HDnAZ7EZ4z6G`
     - includes both safe ``as`` and unsafe ``transmute`` operations
   * - R.11.1
     - UB, IDB
     -
     - includes both safe ``as`` and unsafe ``transmute`` operations
   * - R.11.2
     - UB
     -
     -
   * - R.11.5
     - UB
     -
     -
   * - R.11.6
     - UB, IDB
     - :need:`gui_PM8Vpf7lZ51U`
     -
   * - R.11.8
     - UB
     -
     -
   * - R.12.2
     - UB, DC
     - :need:`gui_LvmzGKdsAgI5`, :need:`gui_RHvQj8BHlz9b`
     -
   * - R.12.4
     - DC
     -
     - this is either well-defined or will not occur
   * - R.14.1
     - DC
     -
     - applies to while loops only
   * - R.17.9
     - UB
     -
     - this is expressed with the ``!`` (Never) type, and enforced by rustc
   * - R.18.1
     - UB
     -
     - by unsafe API
   * - R.18.2
     - UB
     -
     - by unsafe API
   * - R.18.4
     - DC
     -
     - applies to use of the unsafe API
   * - R.18.6
     - UB
     -
     -
   * - R.19.1
     - UB
     -
     -
   * - R.20.4
     - UB
     -
     - possible with raw identifiers but the compiler prevents visual conflicts
   * - R.20.7
     - DC
     -
     - possible to express with procedural macros only, not ``macro_rules``
   * - R.21.3
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.4
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.5
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.6
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.7
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.8
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.9
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.10
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.12
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.13
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.14
     - DC
     -
     - only accessible through unsafe extern "C"
   * - R.21.15
     - DC
     -
     - only accessible through unsafe extern "C"
   * - R.21.16
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.17
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.18
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.19
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.21.20
     - IDB, DC
     -
     - only accessible through unsafe extern "C"
   * - R.21.21
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.21.24
     - CQ
     -
     - only accessible through unsafe extern "C"
   * - R.21.26
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.1
     - UB, CQ
     -
     - applies to resources acquired through FFI only
   * - R.22.2
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.3
     - UB, IDB
     -
     - only accessible through unsafe extern "C"
   * - R.22.4
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.5
     - IDB
     -
     - only accessible through unsafe extern "C"
   * - R.22.6
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.7
     - DC
     -
     - only accessible through unsafe extern "C"
   * - R.22.8
     - DC
     -
     - only accessible through unsafe extern "C"
   * - R.22.9
     - DC
     -
     - only accessible through unsafe extern "C"
   * - R.22.10
     - DC
     -
     - only accessible through unsafe extern "C"
   * - R.22.11
     - UB
     -
     -
   * - R.22.12
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.14
     - UB
     -
     - applies to creating synchronization objects before threads that use them
   * - R.22.15
     - UB
     -
     - applies to releasing synchronization objects after threads that use them
   * - R.22.16
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.17
     - UB
     -
     - only accessible through unsafe extern "C"
   * - R.22.20
     - UB
     -
     -


Table 3 – Guideline rules that are not applicable to Rust
---------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Guideline
     - Rationale
     - Comment
   * - **Directives**
     -
     -
   * - D.4.6
     - DC
     - all primitive types already fulfil this
   * - D.4.8
     - DC
     -
   * - D.4.10
     - UB, DC
     -
   * - **Rules**
     -
     -
   * - R.1.4
     - UB, DC
     - this is specific to C versioning
   * - R.2.4
     - DC
     - no separate tag name space in Rust
   * - R.3.2
     - DC
     -
   * - R.4.1
     - DC, IDB
     -
   * - R.4.2
     - DC
     -
   * - R.5.4
     - UB, IDB, DC
     -
   * - R.5.7
     - UB, DC
     - no separate tag name space in Rust
   * - R.6.1
     - UB, IDB
     - only provided as a library feature
   * - R.6.2
     - DC
     -
   * - R.6.3
     - IDB
     -
   * - R.7.3
     - DC
     -
   * - R.7.4
     - UB
     -
   * - R.7.5
     - UB
     -
   * - R.7.6
     - DC
     -
   * - R.8.1
     - DC
     -
   * - R.8.2
     - UB, DC
     -
   * - R.8.4
     - UB
     -
   * - R.8.8
     - DC
     -
   * - R.8.10
     - UB, DC
     -
   * - R.8.11
     - DC
     -
   * - R.8.12
     - DC
     -
   * - R.8.14
     - UB
     -
   * - R.8.16
     - DC
     - cannot be explicitly specified. Only ZSTs have this alignment
   * - R.8.18
     - UB, DC
     -
   * - R.8.19
     - UB, DC
     -
   * - R.9.2
     - UB, CQ, DC
     -
   * - R.9.3
     - UB
     -
   * - R.9.5
     - IDB, DC
     -
   * - R.9.6
     - DC
     -
   * - R.10.1
     - UB, IDB, DC
     -
   * - R.10.2
     - DC
     -
   * - R.10.3
     - UB, IDB
     -
   * - R.10.4
     - IDB
     -
   * - R.10.6
     - DC
     -
   * - R.10.7
     - DC
     -
   * - R.11.9
     - DC
     - Rust does not have a null pointer constant (specific concept to C)
   * - R.11.10
     - UB
     -
   * - R.12.3
     - DC
     -
   * - R.12.5
     - DC
     -
   * - R.12.6
     - UB
     -
   * - R.13.2
     - UB
     - order of evaluation is strict in Rust
   * - R.13.3
     - UB, DC
     -
   * - R.13.4
     - UB, DC
     - result has unit type and order of evaluation is strict in Rust
   * - R.13.6
     - UB, DC
     - this is not an expression operator in Rust
   * - R.14.2
     - DC
     -
   * - R.15.1
     - DC
     -
   * - R.15.2
     - DC
     -
   * - R.15.3
     - DC
     -
   * - R.15.6
     - DC
     -
   * - R.16.1
     - DC
     -
   * - R.16.2
     - DC
     -
   * - R.16.3
     - DC
     -
   * - R.16.4
     - DC
     - a corresponding match expression must be complete
   * - R.16.5
     - DC
     - irrefutable pattern causes a subsequent refutable one to be unreachable
   * - R.16.6
     - DC
     -
   * - R.16.7
     - DC
     -
   * - R.17.1
     - UB
     -
   * - R.17.3
     - UB
     -
   * - R.17.4
     - UB
     - the return keyword is not needed to return a value in Rust, only to exit
   * - R.17.5
     - UB, DC
     -
   * - R.17.10
     - DC
     -
   * - R.17.12
     - DC
     -
   * - R.17.13
     - UB
     -
   * - R.18.7
     - UB, DC
     -
   * - R.18.8
     - UB, DC
     -
   * - R.18.9
     - UB
     -
   * - R.18.10
     - UB
     -
   * - R.20.1
     - UB
     - rules specific to the C preprocessor do not apply to Rust
   * - R.20.2
     - UB
     -
   * - R.20.3
     - UB
     -
   * - R.20.5
     - DC
     -
   * - R.20.6
     - UB
     -
   * - R.20.8
     - DC
     -
   * - R.20.9
     - DC
     -
   * - R.20.10
     - UB
     -
   * - R.20.11
     - UB
     -
   * - R.20.12
     - DC
     -
   * - R.20.13
     - DC
     -
   * - R.20.14
     - DC
     -
   * - R.20.15
     - UB
     -
   * - R.21.11
     - UB
     - no external interface
   * - R.21.22
     - UB
     - no external interface
   * - R.21.23
     - DC
     - no external interface
   * - R.23.1
     - DC
     -
   * - R.23.2
     - DC
     -
   * - R.23.3
     - DC
     -
   * - R.23.4
     - DC
     -
   * - R.23.5
     - DC
     -
   * - R.23.6
     - DC
     -
   * - R.23.7
     - DC
     -
   * - R.23.8
     - DC
     -


Glossary
========

Rationale
---------

The rationale for each MISRA C guideline is classified with one, or more, of the following:

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Status
     - Interpretation
   * - UB
     - The MISRA C guideline applies to C Undefined or Unspecified Behaviour
   * - IDB
     - The MISRA C guideline applies to C Implementation-defined Behaviour
   * - CQ
     - The MISRA C guideline applies to Code Quality considerations
   * - DC
     - The MISRA C guideline applies to Developer Confusion, where there is common misunderstanding of a C feature


Footnotes
---------

.. rubric:: Footnotes

.. _MISRA C\:2025 Addendum 6: https://misra.org.uk/app/uploads/2025/03/MISRA-C-2025-ADD6.pdf

