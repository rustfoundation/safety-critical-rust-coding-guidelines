.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Macros
======

.. guideline:: Shall not use Declarative Macros
   :id: gui_h0uG1C9ZjryA
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_xa7lp0zg1ol2
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_U3AEUPyaUhcb
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_Gb4zimei8cNI
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_Pw7YCh4Iv47Z
      :status: draft

      Explanation of code example

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Procedural macros should not be used
   :id: gui_66FSqzD55VRZ
   :category: advisory
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_wn1i6hzg2ff7
   :decidability: decidable
   :scope: crate
   :tags: readability, reduce-human-error

   Macros should be expressed using declarative syntax
   in preference to procedural syntax.

   .. rationale::
      :id: rat_AmCavSymv3Ev
      :status: draft

      Procedural macros are not restricted to pure transcription and can contain arbitrary Rust code.
      This means they can be harder to understand, and cannot be as easily proved to work as intended.
      Procedural macros can have arbitrary side effects, which can exhaust compiler resources or
      expose a vulnerability for users of adopted code.

   .. non_compliant_example::
      :id: non_compl_ex_pJhVZW6a1HP9
      :status: draft

      (example of a simple expansion using a proc-macro)

      .. code-block:: rust

        // TODO

   .. compliant_example::
      :id: compl_ex_4VFyucETB7C3
      :status: draft

      (example of the same simple expansion using a declarative macro)

      .. code-block:: rust

        // TODO

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

      Macros are powerful but they come at the cost of readability, complexity, and maintainability. They obfuscate control flow and type signatures.

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
   
      .. code-block:: rust

        macro_rules! increment_and_double {
            ($x:expr) => {
                {
                    $x += 1; // mutation is implicit
                    $x * 2
                }
            };
        }
        let mut num = 5;
        let result = increment_and_double!(num);
        println!("Result: {}, Num: {}", result, num);
        // Result: 12, Num: 6

      In this example, calling the macro both increments and returns the value in one go—without any clear indication in its “signature” that it mutates its argument. As a result, num is changed behind the scenes, which can surprise readers and make debugging more difficult.


   .. compliant_example::
      :id: compl_ex_iPTgzrvO7qr3
      :status: draft

      The same functionality, implemented as a function with explicit borrowing:

      .. code-block:: rust

        fn increment_and_double(x: &mut i32) -> i32 {
            *x += 1; // mutation is explicit 
            *x * 2
        }
        let mut num = 5;
        let result = increment_and_double(&mut num);
        println!("Result: {}, Num: {}", result, num);
        // Result: 12, Num: 6

      The function version makes the mutation and borrowing explicit in its signature, improving readability, safety, and debuggability.

      

.. guideline:: Shall not use Function-like Macros
   :id: gui_WJlWqgIxmE8P
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_utd3zqczix
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_C8RRidiVzhRj
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_TjRiRkmBY6wG
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_AEKEOYhBWPMl
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Shall not invoke macros
   :id: gui_a1mHfjgKk4Xr
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_vnvt40pa48n8
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_62mSorNF05kD
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_hP5KLhqQfDcd
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_ti7GWHCOhUvT
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Shall not write code that expands macros
   :id: gui_uuDOArzyO3Qw
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_wjldgtio5o75
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_dNgSvC0SZ3JJ
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_g9j8shyGM2Rh
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_cFPg6y7upNdl
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Shall ensure complete hygiene of macros
   :id: gui_8hs33nyp0ipX
   :category: mandatory
   :status: draft
   :release: todo
   :fls: fls_xlfo7di0gsqz
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale::
      :id: rat_e9iS187skbHH
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_lRt4LBen6Lkc
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_GLP05s9c1g8N
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Attribute macros shall not be used
   :id: gui_13XWp3mb0g2P
   :category: required
   :status: draft
   :release: todo
   :fls: fls_4vjbkm4ceymk
   :decidability: decidable
   :scope: system
   :tags: reduce-human-error

   Attribute macros shall neither be declared nor invoked.
   Prefer less powerful macros that only extend source code.

   .. rationale:: 
      :id: rat_X8uCF5yx7Mpo
      :status: draft

      Attribute macros are able to rewrite items entirely or in other unexpected ways which can cause confusion and introduce errors.

   .. non_compliant_example::
      :id: non_compl_ex_eW374waRPbeL
      :status: draft

      Explanation of code example.
   
      .. code-block:: rust
   
        #[tokio::main]  // non-compliant
        async fn main() {

        }

   .. compliant_example::
      :id: compl_ex_Mg8ePOgbGJeW
      :status: draft

      Explanation of code example.
   
      .. code-block:: rust
   
        fn example_function() {
            // Compliant implementation
        }
   
.. guideline:: Do not hide unsafe blocks within macro expansions
   :id: gui_FRLaMIMb4t3S                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                
   :category: required                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          
   :status: draft                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       
   :release: todo                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           
   :fls: fls_4vjbkm4ceymk
   :decidability: todo
   :scope: todo
   :tags: reduce-human-error

   Description of the guideline goes here.

   .. rationale:: 
      :id: rat_WJubG7KuUDLW
      :status: draft

      Explanation of why this guideline is important.

   .. non_compliant_example::
      :id: non_compl_ex_AyFnP0lJLHxi
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Non-compliant implementation
        }

   .. compliant_example::
      :id: compl_ex_pO5gP1aj2v4F
      :status: draft

      Explanation of code example.

      .. code-block:: rust

        fn example_function() {
            // Compliant implementation
        }

.. guideline:: Names in a macro definition shall use a fully qualified path
   :id: gui_SJMrWDYZ0dN4
   :category: required
   :status: draft
   :release: 1.85.0;1.85.1
   :fls: fls_7kb6ltajgiou
   :decidability: decidable
   :scope: module
   :tags: reduce-human-error

   Each name inside of the definition of a macro shall either use a global path or path prefixed with $crate.

   .. rationale::
      :id: rat_VRNXaxmW1l2s
      :status: draft

      Using a path that refers to an entity relatively inside of a macro subjects it to path resolution
      results which may change depending on where the macro is used. The intended path to refer to an entity
      can be shadowed when using a macro leading to unexpected behaviors. This could lead to developer confusion
      about why a macro behaves differently in diffenent locations, or confusion about where entity in a macro
      will resolve to.

   .. non_compliant_example::
      :id: non_compl_ex_m2XR1ihTbCQS
      :status: draft

      The following is a macro which shows referring to a vector entity using a non-global path. Depending on
      where the macro is used a different `Vec` could be used than is intended. If scope where this is used
      defines a struct `Vec` which is not preset at the macro defintion, the macro user might be intending to
      use that in the macro.

      .. code-block:: rust

        #[macro_export]
        macro_rules! vec {
            ( $( $x:expr ),* ) => {
                {
                    let mut temp_vec = Vec::new(); // non-global path
                    $(
                        temp_vec.push($x);
                    )*
                    temp_vec
                }
            };
        }

   .. compliant_example::
      :id: compl_ex_xyaShvxL9JAM
      :status: draft

      The following is a macro refers to Vec using a global path. Even if there is a different struct called
      `Vec` defined in the scope of the macro usage, this macro will unambigiously use the `Vec` from the
      Standard Library.

      .. code-block:: rust

        #[macro_export]
        macro_rules! vec {
            ( $( $x:expr ),* ) => {
                {
                    let mut temp_vec = ::std::vec::Vec::new(); // global path
                    $(
                        temp_vec.push($x);
                    )*
                    temp_vec
                }
            };
        }
