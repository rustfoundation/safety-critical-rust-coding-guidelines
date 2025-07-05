import json
import sys 
import os 
import subprocess

def print_code_snippet(file_path, line_num, context=3):
    """
    Prints a code snippet from a file with context around a specific line.

    This function is typically used to display source code around an error line
    for better debugging and error reporting.

    Args:
        file_path (str): Path to the source file.
        line_num (int): The line number where the error occurred (1-based index).
        context (int, optional): The number of lines to display before and after
            the error line. Defaults to 3.

    Returns:
        None
    """
    try:
        stripped_lines = []
        with open(file_path, "r") as f:
            lines = f.readlines()
            start = max(line_num - context - 1, 0)  
            end = min(line_num + context, len(lines))
            for i in range(start, end):
                prefix = ">" if i == line_num - 1 else " "
                stripped_lines.append(f"{prefix} {i+1:4}: {lines[i].rstrip()}")
            return "\n".join(stripped_lines)
    except Exception as e:
        print(f"Could not read file {file_path}: {e}")

    
import json

def parse_cargo_errors(output: str, output_rust):
    """
    Parses Cargo’s JSON output and prints only the first compiler error it finds.
    Ignores warnings and notes entirely.
    """
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Only look at compiler messages
        if rec.get("reason") != "compiler-message":
            continue

        msg = rec["message"]
        # Skip anything that isn't an error
        if msg.get("level") != "error":
            continue

        text = msg.get("message", "")
        spans = msg.get("spans", [])

        # Print the high-level error first
        print(f"\nerror: {text}")

        # Then try to show its primary location
        for span in spans:
            if span.get("is_primary"):
                file = span.get("file_name")
                line_start = span.get("line_start")
                label = span.get("label", "")
                print(f"  --> {file}:{line_start} {label}".rstrip(), file= sys.stderr)
                # and a snippet
                snippet = print_code_snippet(output_rust + file, line_start, context=5)
                print("\n" + snippet, file = sys.stderr)
                break

        # Stop after the first error
        return

def check_rust_test_errors(app, exception):
    """
    Sphinx 'build-finished' event handler that compiles the generated Rust file in test mode.

    This function is connected to the Sphinx build lifecycle and is executed after the build finishes.
    It invokes `rustc` in test mode on the generated Rust file and reports any compilation or test-related
    errors.
    """
    rs_path = app.output_rust
    cargo_toml_path = os.path.join(rs_path, "Cargo.toml")
    # Run the Rust compiler in test mode with JSON error output format.
    # capturing stdout and stderr as text.
    result = subprocess.run(
        [
            "cargo",
            "test",
            "--message-format=json",
            "--manifest-path",
            cargo_toml_path
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("\033[31m--- Cargo test errors ---\033[0m")
        parse_cargo_errors(result.stdout, app.output_rust)  # parse stdout JSON lines
        # print("--- rustc Output ---")
        # print(result.stdout)
    else:
        print("\033[1;32mAll tests succeeded\033[0m") # ANSI magic
        # print(result.stdout)
        # if result.stderr:
            # print("\n\n--- rustc Warnings ---")
            # print(result.stderr)
