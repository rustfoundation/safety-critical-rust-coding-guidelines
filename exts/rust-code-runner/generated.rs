// ==== Code Block 1 ====
#[test]
fn test_block_coding_guidelines_expressions_1() {
             #[repr(C)]
             struct Base {
                position: (u32, u32)
             }
}

// ==== Code Block 2 ====
#[test]
fn test_block_coding_guidelines_expressions_2() {
             #[repr(C)]
             struct Base {
                position: (u32, u32)
             }
}

// ==== Code Block 1 ====
#[test]
fn test_block_coding_guidelines_macros_1() {
            fn example_function() {
                // Non-compliant implementation
            }
}

// ==== Code Block 2 ====
#[test]
fn test_block_coding_guidelines_macros_2() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 3 ====
#[test]
fn test_block_coding_guidelines_macros_3() {
            // TODO
}

// ==== Code Block 4 ====
#[test]
fn test_block_coding_guidelines_macros_4() {
            // TODO
}

// ==== Code Block 5 ====
#[test]
fn test_block_coding_guidelines_macros_5() {
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
}

// ==== Code Block 6 ====
#[test]
fn test_block_coding_guidelines_macros_6() {
            fn increment_and_double(x: &mut i32) -> i32 {
                *x += 1; // mutation is explicit
                *x * 2
            }
            let mut num = 5;
            let result = increment_and_double(&mut num);
            println!("Result: {}, Num: {}", result, num);
            // Result: 12, Num: 6
}

// ==== Code Block 7 ====
#[test]
fn test_block_coding_guidelines_macros_7() {
            fn example_function() {
                // Non-compliant implementation
            }
}

// ==== Code Block 8 ====
#[test]
fn test_block_coding_guidelines_macros_8() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 9 ====
#[test]
fn test_block_coding_guidelines_macros_9() {
            fn example_function() {
                // Non-compliant implementation
            }
}

// ==== Code Block 10 ====
#[test]
fn test_block_coding_guidelines_macros_10() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 11 ====
#[test]
fn test_block_coding_guidelines_macros_11() {
            fn example_function() {
                // Non-compliant implementation
            }
}

// ==== Code Block 12 ====
#[test]
fn test_block_coding_guidelines_macros_12() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 13 ====
#[test]
fn test_block_coding_guidelines_macros_13() {
            fn example_function() {
                // Non-compliant implementation
            }
}

// ==== Code Block 14 ====
#[test]
fn test_block_coding_guidelines_macros_14() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 15 ====
#[test]
fn test_block_coding_guidelines_macros_15() {
            #[tokio::main]  // non-compliant
            async fn main() {
}

// ==== Code Block 16 ====
#[test]
fn test_block_coding_guidelines_macros_16() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 17 ====
#[test]
fn test_block_coding_guidelines_macros_17() {
            fn example_function() {
                // Non-compliant implementation
            }
}

// ==== Code Block 18 ====
#[test]
fn test_block_coding_guidelines_macros_18() {
            fn example_function() {
                // Compliant implementation
            }
}

// ==== Code Block 19 ====
#[test]
fn test_block_coding_guidelines_macros_19() {
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
}

// ==== Code Block 20 ====
#[test]
fn test_block_coding_guidelines_macros_20() {
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
}

// ==== Code Block 1 ====
#[test]
fn test_block_coding_guidelines_types_and_traits_1() {
             fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                 // Potential for silent overflow in release builds
                 current + velocity
             }
}

// ==== Code Block 2 ====
#[test]
fn test_block_coding_guidelines_types_and_traits_2() {
             fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                 // Explicitly handle potential overflow with checked addition
                 current.checked_add(velocity).expect("Position calculation overflowed")
             }
}

// ==== Code Block 1 ====
#[test]
fn test_block_process_style_guideline_1() {
                fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                    // Potential for silent overflow in release builds
                    current + velocity
                }
}

// ==== Code Block 2 ====
#[test]
fn test_block_process_style_guideline_2() {
                fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                    // Explicitly handle potential overflow with checked addition
                    current.checked_add(velocity).expect("Position calculation overflowed")
                }
}

// ==== Code Block 3 ====
#[test]
fn test_block_process_style_guideline_3() {
                fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                    // Potential for silent overflow in release builds
                    current + velocity
                }
}

// ==== Code Block 4 ====
#[test]
fn test_block_process_style_guideline_4() {
                fn calculate_next_position(current: u32, velocity: u32) -> u32 {
                    // Explicitly handle potential overflow with checked addition
                    current.checked_add(velocity).expect("Position calculation overflowed")
                }
}

