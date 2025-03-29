.. SPDX-License-Identifier: MIT OR Apache-2.0
   SPDX-FileCopyrightText: The Coding Guidelines Subcommittee Contributors

.. default-domain:: coding-guidelines

Macros
======

.. guideline:: Avoid specialized, fixed patterns within declarative macros
   :id: gui_FSpI084vbwmJ
   :category: required
   :status: draft
   :fls: fls_w44hav7mw3ao
   :decidability: decidable
   :scope: module
   :tags: reduce-human-error

    Matchers within macro rules are evaluated sequentially and short-circuit on
    the first match. If a specialized fixed matcher follows a broader matcher,
    it may be unreachable. This can lead to subtle and surprising bugs. It is
    encouraged to avoid the use of specialized, fixed matchers.

   .. rationale::
      :id: rat_zqr9uEqP6nzW
      :status: draft

      It's common to use macros to avoid writing repetitive code, such as trait
      implementations. It's possible to use derive macros or declarative macros
      to do so.

      In a declarative macro the ordering of the patterns will be the order that
      they are matched against which can lead to unexpected behavior in the case
      where we have unique behavior intended for a particular expression.

      If needing to specialize logic within the macro based on a particular
      expression's value, it is better to not use a declarative macro.

   .. non_compliant_example::
      :id: non_compl_ex_5vK0CCmePkef
      :status: draft

      We have two macro match rules at the same level of nesting. Since macro
      matching is done sequentially through the matchers and stops at the first 
      match, the specialized case for EmergencyValve is unreachable.

      The example would also be non-compliant if the ordering of the matchers
      were reversed as this introduces the possibility of future human-error
      when refactoring the macro to place the specialized matcher after the
      generic matcher.

      .. code-block:: rust

         #[derive(Debug)]
         enum SafetyLevel {
             Green,
             Yellow,
             Red
         }

         trait SafetyCheck {
             fn verify(&self) -> SafetyLevel;
         }

         // Different device types that need safety checks
         struct PressureSensor {/* ... */}
         struct TemperatureSensor {/* ... */}
         struct EmergencyValve {
             open: bool,
         }

         // This macro has a pattern ordering issue
         macro_rules! impl_safety_trait {
             // Generic pattern matches any type - including EmergencyValve
             ($t:ty) => {
                 impl SafetyCheck for $t {
                     fn verify(&self) -> SafetyLevel {
                         SafetyLevel::Green
                     }
                 }
             };

             // Special pattern for EmergencyValve - but never gets matched
             (EmergencyValve) => {
                 impl SafetyCheck for EmergencyValve {
                     fn verify(&self) -> SafetyLevel {
                         // Emergency valve must be open for safety
                         if !self.open {
                             SafetyLevel::Red
                         } else {
                             SafetyLevel::Green
                         }
                     }
                 }
             };
         }
         impl_safety_trait!(EmergencyValve);
         impl_safety_trait!(PressureSensor);
         impl_safety_trait!(TemperatureSensor);

   .. compliant_example::
      :id: compl_ex_ILBlY8DKB6Vs
      :status: draft

      For the specialized implementation we implement the trait directly.

      If we wish to use a declarative macro for a certain generic implementation
      we are able to do this. Note there is a single macro rule at the level of
      nesting within the declarative macro.

      .. code-block:: rust

         #[derive(Debug)]
         enum SafetyLevel {
             Green,
             Yellow,
             Red
         }

         trait SafetyCheck {
             fn verify(&self) -> SafetyLevel;
         }

         // Different device types that need safety checks
         struct PressureSensor {/* ... */}
         struct TemperatureSensor {/* ... */}
         struct EmergencyValve {
             open: bool,
         }

         // Direct implementation for EmergencyValve
         impl SafetyCheck for EmergencyValve {
             fn verify(&self) -> SafetyLevel {
                 // Emergency valve must be open for safety
                 if !self.open {
                     SafetyLevel::Red
                 } else {
                     SafetyLevel::Green
                 }
             }
         }

         // Use generic implementation for those without
         // special behavior
         macro_rules! impl_safety_traits_generic {
             // Generic pattern for other types
             ($t:ty) => {
                 impl SafetyCheck for $t {
                     fn verify(&self) -> SafetyLevel {
                         SafetyLevel::Green
                     }
                 }
             };
         }
         impl_safety_traits_generic!(PressureSensor);
         impl_safety_traits_generic!(TemperatureSensor);
