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
     - Category
     - Safety critical Rust rule
     - Comment
   * - **Directives**
     -
     -
     -
   * - D.1.1
     - Required
     - 
     -
   * - D.1.2
     - Advisory
     -
     - intended to apply to experimental and unstable features, forcing full documentation
   * - D.2.1
     - Required
     -
     -
   * - D.3.1
     - Required
     -
     -
   * - D.4.1
     - Required
     -
     - often in the form of panics
   * - D.4.4
     - Advisory
     -
     - conditional compilation is provided by the cfg attribute
   * - D.4.5
     - Advisory
     -
     - "ambiguity" is determined by the project
   * - D.4.7
     - Required
     -
     - prefer Option, Result, etc. over in-band error values
   * - D.4.9
     - Advisory
     -
     -
   * - D.4.11
     - Required
     -
     -
   * - D.4.12
     - Required
     -
     -
   * - D.4.13
     - Advisory
     -
     - many Rust APIs use the type system to enforce ordering
   * - D.4.14
     - Required
     -
     -
   * - D.4.15
     - Required
     -
     - Rust implements IEEE-754
   * - D.5.2
     - Required
     -
     -
   * - D.5.3
     - Required
     -
     -
   * - **Rules**
     -
     -
     -
   * - R.1.3
     - Required
     -
     -
   * - R.1.5
     - Required
     -
     - this applies to deprecated APIs
   * - R.2.1
     - Required
     -
     -
   * - R.2.2
     - Required
     -
     -
   * - R.2.3
     - Advisory
     -
     -
   * - R.2.5
     - Advisory
     -
     -
   * - R.2.6
     - Advisory
     -
     -
   * - R.2.7
     - Advisory
     -
     -
   * - R.2.8
     - Advisory
     -
     -
   * - R.3.1
     - Required
     -
     - nested comments are fully supported
   * - R.5.2
     - Required
     -
     - no character limit, but one can be applied; has name spaces
   * - R.5.3
     - Required
     - :need:`gui_SJMrWDYZ0dN4`
     - this also applies to macro names
   * - R.5.6
     - Required
     -
     - the proper module system makes surprise name conflicts much less likely
   * - R.5.8
     - Required
     -
     - the proper module system makes surprise name conflicts much less likely
   * - R.5.9
     - Advisory
     -
     -
   * - R.7.1
     - Required
     -
     - Rust octals have a distinct prefix from decimals
   * - R.7.2
     - Required
     -
     - this is an error by default but can be enabled. Note that suffixes also make the size explicit
   * - R.8.7
     - Advisory
     -
     - items should not be declared pub if referenced in only one module
   * - R.8.9
     - Advisory
     -
     -
   * - R.8.13
     - Advisory
     -
     - ``mut`` should be avoided unless necessary
   * - R.9.1
     - Mandatory
     -
     - enforced by rustc but can be bypassed by unsafe
   * - R.9.4
     - Required
     -
     - enforced by rustc
   * - R.11.3
     - Required
     -
     -
   * - R.11.4
     - Advisory
     - :need:`gui_PM8Vpf7lZ51U`
     -
   * - R.11.11
     - Advisory
     -
     - enforced by rustc
   * - R.12.1
     - Advisory
     -
     -
   * - R.13.1
     - Required
     -
     - order of evaluation is strict in Rust
   * - R.13.5
     - Required
     -
     -
   * - R.14.3
     - Required
     -
     -
   * - R.14.4
     - Required
     -
     - enforced by rustc
   * - R.15.4
     - Advisory
     -
     -
   * - R.15.5
     - Advisory
     -
     -
   * - R.15.7
     - Required
     -
     -
   * - R.17.2
     - Required
     - :need:`gui_ot2Zt3dd6of1`
     -
   * - R.17.7
     - Required
     -
     - ``must_use`` can help indicate where this is important, but does not affect applicability
   * - R.17.8
     - Advisory
     -
     - this cannot be done accidentally without declaring parameters ``mut``
   * - R.17.11
     - Advisory
     -
     - a non-returning function can be declared to return a value type
   * - R.18.3
     - Required
     -
     -
   * - R.18.5
     - Advisory
     -
     -
   * - R.19.2
     - Advisory
     - :need:`gui_0cuTYG8RVYjg`
     -
   * - R.19.3
     - Required
     -
     -
   * - R.21.25
     - Required
     -
     -
   * - R.22.13
     - Required
     -
     -
   * - R.22.18
     - Required
     -
     -
   * - R.22.19
     - Required
     -
     -


Table 2 – Guidelines applicable to Rust in the presence of unsafe code
-----------------------------------------------------------------------

In addition to the rules from Table 1, these are the additional guidelines that need to be covered:

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Guideline
     - Category
     - Safety critical Rust rule
     - Comment
   * - **Directives**
     -
     -
     -
   * - D.4.2
     - Advisory
     -
     -
   * - D.4.3
     - Required
     -
     -
   * - D.5.1
     - Required
     -
     - not all safe Rust types are race-free
   * - **Rules**
     -
     -
     -
   * - R.1.1
     - Required
     -
     -
   * - R.5.1
     - Required
     -
     - no character limit, except in extern "C", but one can be set by project
   * - R.5.5
     - Required
     -
     - macros and functions use different syntax
   * - R.5.10
     - Required
     -
     - only possible in some cases. Previously Rule 21.2
   * - R.8.3
     - Required
     -
     - an extern declaration shall have a type compatible with the C declaration
   * - R.8.5
     - Required
     -
     - may affect extern "C" declarations
   * - R.8.6
     - Required
     -
     - may affect extern "C" declarations
   * - R.8.15
     - Required
     -
     - may affect extern "C" declarations
   * - R.8.17
     - Advisory
     -
     - alignment applies to types, not objects
   * - R.9.7
     - Mandatory
     -
     -
   * - R.10.5
     - Advisory
     - :need:`gui_ADHABsmK9FXz`
     - includes both safe ``as`` and unsafe ``transmute`` operations
   * - R.10.8
     - Required
     - :need:`gui_HDnAZ7EZ4z6G`
     - includes both safe ``as`` and unsafe ``transmute`` operations
   * - R.11.1
     - Required
     -
     - includes both safe ``as`` and unsafe ``transmute`` operations
   * - R.11.2
     - Required
     -
     -
   * - R.11.5
     - Advisory
     -
     -
   * - R.11.6
     - Required
     - :need:`gui_PM8Vpf7lZ51U`
     -
   * - R.11.8
     - Required
     -
     -
   * - R.12.2
     - Required
     - :need:`gui_LvmzGKdsAgI5`, :need:`gui_RHvQj8BHlz9b`
     -
   * - R.12.4
     - Advisory
     -
     - this is either well-defined or will not occur
   * - R.14.1
     - Required
     -
     - applies to while loops only
   * - R.17.9
     - Mandatory
     -
     - this is expressed with the ``!`` (Never) type, and enforced by rustc
   * - R.18.1
     - Required
     -
     - by unsafe API
   * - R.18.2
     - Required
     -
     - by unsafe API
   * - R.18.4
     - Advisory
     -
     - applies to use of the unsafe API
   * - R.18.6
     - Required
     -
     -
   * - R.19.1
     - Mandatory
     -
     -
   * - R.20.4
     - Required
     -
     - possible with raw identifiers but the compiler prevents visual conflicts
   * - R.20.7
     - Required
     -
     - possible to express with procedural macros only, not ``macro_rules``
   * - R.21.3
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.4
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.5
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.6
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.7
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.8
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.9
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.10
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.12
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.13
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.21.14
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.15
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.16
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.17
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.21.18
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.21.19
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.21.20
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.21.21
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.24
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.21.26
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.1
     - Required
     -
     - applies to resources acquired through FFI only
   * - R.22.2
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.22.3
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.4
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.22.5
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.22.6
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.22.7
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.8
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.9
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.10
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.11
     - Required
     -
     -
   * - R.22.12
     - Mandatory
     -
     - only accessible through unsafe extern "C"
   * - R.22.14
     - Mandatory
     -
     - applies to creating synchronization objects before threads that use them
   * - R.22.15
     - Required
     -
     - applies to releasing synchronization objects after threads that use them
   * - R.22.16
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.17
     - Required
     -
     - only accessible through unsafe extern "C"
   * - R.22.20
     - Mandatory
     -
     -


Table 3 – Guideline rules that are not applicable to Rust
---------------------------------------------------------

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Guideline
     - Category
     - Comment
   * - **Directives**
     -
     -
   * - D.4.6
     - Advisory
     - all primitive types already fulfil this
   * - D.4.8
     - Advisory
     -
   * - D.4.10
     - Required
     -
   * - **Rules**
     -
     -
   * - R.1.4
     - Required
     - this is specific to C versioning
   * - R.2.4
     - Advisory
     - no separate tag name space in Rust
   * - R.3.2
     - Required
     -
   * - R.4.1
     - Required
     -
   * - R.4.2
     - Advisory
     -
   * - R.5.4
     - Required
     -
   * - R.5.7
     - Required
     - no separate tag name space in Rust
   * - R.6.1
     - Required
     - only provided as a library feature
   * - R.6.2
     - Required
     -
   * - R.6.3
     - Required
     -
   * - R.7.3
     - Required
     -
   * - R.7.4
     - Required
     -
   * - R.7.5
     - Mandatory
     -
   * - R.7.6
     - Required
     -
   * - R.8.1
     - Required
     -
   * - R.8.2
     - Required
     -
   * - R.8.4
     - Required
     -
   * - R.8.8
     - Required
     -
   * - R.8.10
     - Required
     -
   * - R.8.11
     - Advisory
     -
   * - R.8.12
     - Required
     -
   * - R.8.14
     - Required
     -
   * - R.8.16
     - Advisory
     - cannot be explicitly specified. Only ZSTs have this alignment
   * - R.8.18
     - Required
     -
   * - R.8.19
     - Advisory
     -
   * - R.9.2
     - Required
     -
   * - R.9.3
     - Required
     -
   * - R.9.5
     - Required
     -
   * - R.9.6
     - Required
     -
   * - R.10.1
     - Required
     -
   * - R.10.2
     - Required
     -
   * - R.10.3
     - Required
     -
   * - R.10.4
     - Required
     -
   * - R.10.6
     - Required
     -
   * - R.10.7
     - Required
     -
   * - R.11.9
     - Required
     - Rust does not have a null pointer constant (specific concept to C)
   * - R.11.10
     - Required
     -
   * - R.12.3
     - Advisory
     -
   * - R.12.5
     - Mandatory
     -
   * - R.12.6
     - Required
     -
   * - R.13.2
     - Required
     - order of evaluation is strict in Rust
   * - R.13.3
     - Advisory
     -
   * - R.13.4
     - Advisory
     - result has unit type and order of evaluation is strict in Rust
   * - R.13.6
     - Required
     - this is not an expression operator in Rust
   * - R.14.2
     - Required
     -
   * - R.15.1
     - Advisory
     -
   * - R.15.2
     - Required
     -
   * - R.15.3
     - Required
     -
   * - R.15.6
     - Required
     -
   * - R.16.1
     - Required
     -
   * - R.16.2
     - Required
     -
   * - R.16.3
     - Required
     -
   * - R.16.4
     - Required
     - a corresponding match expression must be complete
   * - R.16.5
     - Required
     - irrefutable pattern causes a subsequent refutable one to be unreachable
   * - R.16.6
     - Required
     -
   * - R.16.7
     - Required
     -
   * - R.17.1
     - Required
     -
   * - R.17.3
     - Mandatory
     -
   * - R.17.4
     - Mandatory
     - the return keyword is not needed to return a value in Rust, only to exit
   * - R.17.5
     - Required
     -
   * - R.17.10
     - Required
     -
   * - R.17.12
     - Advisory
     -
   * - R.17.13
     - Required
     -
   * - R.18.7
     - Required
     -
   * - R.18.8
     - Required
     -
   * - R.18.9
     - Required
     -
   * - R.18.10
     - Mandatory
     -
   * - R.20.1
     - Advisory
     - rules specific to the C preprocessor do not apply to Rust
   * - R.20.2
     - Required
     -
   * - R.20.3
     - Required
     -
   * - R.20.5
     - Advisory
     -
   * - R.20.6
     - Required
     -
   * - R.20.8
     - Required
     -
   * - R.20.9
     - Required
     -
   * - R.20.10
     - Advisory
     -
   * - R.20.11
     - Required
     -
   * - R.20.12
     - Required
     -
   * - R.20.13
     - Required
     -
   * - R.20.14
     - Required
     -
   * - R.20.15
     - Required
     -
   * - R.21.11
     - Advisory
     - no external interface
   * - R.21.22
     - Mandatory
     - no external interface
   * - R.21.23
     - Required
     - no external interface
   * - R.23.1
     - Advisory
     -
   * - R.23.2
     - Required
     -
   * - R.23.3
     - Advisory
     -
   * - R.23.4
     - Required
     -
   * - R.23.5
     - Advisory
     -
   * - R.23.6
     - Required
     -
   * - R.23.7
     - Advisory
     -
   * - R.23.8
     - Required
     -


Glossary
--------

Category
........

Each MISRA C guideline is assigned a category, as follows:

.. list-table::
   :header-rows: 1
   :widths: auto

   * - Category
     - Interpretation
   * - Mandatory
     - Code shall always comply with this guideline. Formal deviation is not permitted
   * - Required
     - Code shall comply with this guideline, with a formal deviation required where this is not the case
   * - Advisory
     - These are recommendations which should be followed as far as is reasonably practical. Formal deviation is not necessary for advisory guidelines but, if the formal deviation process is not followed, alternative arrangements should be made for documenting non-compliances


Footnotes
.........

.. rubric:: Footnotes

.. _MISRA C\:2025 Addendum 6: https://misra.org.uk/app/uploads/2025/03/MISRA-C-2025-ADD6.pdf

