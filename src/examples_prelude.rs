// SPDX-License-Identifier: MIT OR Apache-2.0
// SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

//! Shared prelude for coding guideline examples.
//!
//! This file contains common utilities that are implicitly
//! available to all code examples in the documentation. These are
//! prepended as hidden lines when testing examples.
//!
//! Note: Type definitions like ArithmeticError and DivError are defined
//! as hidden lines within individual examples to keep them self-contained.

/// A placeholder function that does nothing.
/// Use this in examples where you need to call a function but
/// the implementation doesn't matter.
pub fn placeholder() {}

/// A placeholder function that takes any argument.
pub fn use_value<T>(_value: T) {}

/// Macro to suppress unused variable warnings in examples.
#[macro_export]
macro_rules! ignore {
    ($($x:tt)*) => { let _ = { $($x)* }; };
}
