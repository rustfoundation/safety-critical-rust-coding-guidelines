.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

.. guideline:: A macro should not be used in place of a function
   :id: gui_2jjWUoF1teOY
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_xa7lp0zg1ol2
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Functions should always be preferred over macros, except when macros provide essential functionality that functions cannot, such as variadic interfaces, compile-time code generation, or syntax extensions via custom derive and attribute macros.

   |

   .. rationale::
      :id: rat_M9bp23ctkzQ7
      :status: draft

      Although the compiler reports both the macro expansion and its invocation site, diagnostics originating within macros can be more difficult to interpret than those from ordinary function or type definitions. Complex or deeply nested macros may obscure intent and hinder static analysis, increasing the risk of misinterpretation or overlooked errors during code review.


      **Debugging Complexity**

      - Errors point to expanded code rather than source locations, making it difficult to trace compile-time errors back to the original macro invocation.

      **Optimization**

      - Macros may inhibit compiler optimizations that work better with functions.
      - Macros act like ``#[inline(always)]`` functions, which can lead to code bloat.
      - They don't benefit from the compiler's inlining heuristics, missing out on selective inlining where the compiler decides when inlining is beneficial.

      **Functions provide**

      - Clear type signatures.
      - Predictable behavior.
      - Proper stack traces.
      - Consistent optimization opportunities.


   .. non_compliant_example::
      :id: non_compl_ex_TZgk2vG42t2r
      :status: draft

      Using a macro where a simple function would suffice, leads to hidden mutation:

      .. rust-example::

        macro_rules! increment_and_double {
            ($x:expr) => {
                {
                    $x += 1; // mutation is implicit
                    $x * 2
                }
            };
        }

        fn main() {
            let mut num = 5;
            let result = increment_and_double!(num);
            println!("Result: {}, Num: {}", result, num);
            // Result: 12, Num: 6
        }

      In this example, calling the macro both increments and returns the value in one go—without any clear indication in its "signature" that it mutates its argument. As a result, num is changed behind the scenes, which can surprise readers and make debugging more difficult.


   .. compliant_example::
      :id: compl_ex_iPTgzrvO7qr3
      :status: draft

      The same functionality, implemented as a function with explicit borrowing:

      .. rust-example::

        fn increment_and_double(x: &mut i32) -> i32 {
            *x += 1; // mutation is explicit
            *x * 2
        }

        fn main() {
            let mut num = 5;
            let result = increment_and_double(&mut num);
            println!("Result: {}, Num: {}", result, num);
            // Result: 12, Num: 6
        }

      The function version makes the mutation and borrowing explicit in its signature, improving readability, safety, and debuggability.
