.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. This file contains test examples to verify the rust-example directive options work correctly.
   These examples are designed to test the :edition:, :version:, and :channel: options.

=======================================
Test Examples for Directive Validation
=======================================

This file contains examples specifically designed to test that the ``rust-example`` directive 
options (`:edition:`, `:version:`, `:channel:`) work correctly.

Edition Examples
================

.. guideline:: Test edition 2021 (default)
   :id: gui_test_edition_2021
   :category: advisory
   :status: draft
   :release: test

   Example using Rust 2021 edition (the default).

   .. rust-example::

      fn main() {
          // 2021 edition - closures capture only what they use
          let s = String::from("hello");
          let closure = || println!("{}", s);
          closure();
      }

.. guideline:: Test edition 2018 explicit
   :id: gui_test_edition_2018
   :category: advisory
   :status: draft
   :release: test

   Example explicitly using Rust 2018 edition.

   .. rust-example::
       :edition: 2018

      fn main() {
          // 2018 edition syntax works
          let v: Vec<i32> = vec![1, 2, 3];
          for i in &v {
              println!("{}", i);
          }
      }

.. guideline:: Test edition 2015
   :id: gui_test_edition_2015
   :category: advisory
   :status: draft
   :release: test

   Example using Rust 2015 edition.

   .. rust-example::
       :edition: 2015

      fn main() {
          // 2015 edition - basic syntax
          let x = 5;
          println!("{}", x);
      }

Version Examples
================

.. guideline:: Test version requirement
   :id: gui_test_version_requirement
   :category: advisory
   :status: draft
   :release: test

   Example requiring a specific minimum Rust version. This example uses ``std::num::NonZero``
   which was stabilized in Rust 1.79.

   .. rust-example::
       :version: 1.79

      use std::num::NonZero;

      fn main() {
          if let Some(n) = NonZero::<u32>::new(42) {
              println!("Got non-zero: {}", n);
          }
      }

.. guideline:: Test newer version requirement
   :id: gui_test_version_newer
   :category: advisory
   :status: draft
   :release: test

   Example requiring Rust 1.87+ for ``unbounded_shl``/``unbounded_shr`` methods.

   .. rust-example::
       :version: 1.87

      fn main() {
          let x: u32 = 0b1010;
          // unbounded_shl was stabilized in 1.87
          let shifted = x.unbounded_shl(2);
          println!("Shifted: {}", shifted);
      }

Channel Examples
================

.. guideline:: Test nightly channel requirement
   :id: gui_test_nightly_channel
   :category: advisory
   :status: draft
   :release: test

   Example requiring nightly channel. This uses a feature that's only available on nightly.
   Note: This example uses ``#![feature(...)]`` which requires nightly.

   .. rust-example::
       :channel: nightly

      #![feature(test)]

      fn main() {
          // The test feature is permanently unstable
          println!("This requires nightly");
      }

Combined Options
================

.. guideline:: Test combined edition and version
   :id: gui_test_combined_options
   :category: advisory
   :status: draft
   :release: test

   Example combining edition and version requirements.

   .. rust-example::
       :edition: 2021
       :version: 1.79

      use std::num::NonZero;

      fn main() {
          // Combines 2021 edition with 1.79+ version requirement
          let maybe_zero = 0u32;
          match NonZero::new(maybe_zero) {
              Some(n) => println!("Non-zero: {}", n),
              None => println!("Was zero"),
          }
      }

Standard Example (No Special Options)
=====================================

.. guideline:: Test standard example
   :id: gui_test_standard
   :category: advisory
   :status: draft
   :release: test

   A standard example with no special options - uses defaults (edition 2021, stable channel).

   .. rust-example::

      fn main() {
          let message = "Hello from a standard example";
          println!("{}", message);
      }
