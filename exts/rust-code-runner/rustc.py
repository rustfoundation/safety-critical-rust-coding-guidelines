import json
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

    
def parse_rustc_json(stderr: str, file_path):
    """
    Parses rustc's JSON output and prints only the first error with a single snippet.

    Args:
        stderr (str): JSON-formatted stderr output from rustc.
        file_path: Path to the Rust file.

    Returns:
        None
    """
    for line in stderr.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            diagnostic = json.loads(line)
        except json.JSONDecodeError:
            continue

        if diagnostic.get("$message_type") != "diagnostic":
            continue

        if diagnostic.get("level") != "error":
            continue  # skip warnings and notes

        message = diagnostic.get("message", "")
        spans = diagnostic.get("spans", [])

        # Try to find a span in the current file
        for span in spans:
            if span["file_name"] == file_path:
                line_num = span["line_start"]
                label = span.get("label", "")
                print(f"error: line {line_num}: {message}")
                if label:
                    print(f"--> {label}")
                print("=" * 25)
                snippet = print_code_snippet(file_path, line_num, context=3)
                print(snippet)
                print("=" * 25)
                return  # we return because we only print the first error--in json format there can be multiple error messages for 1 error-- if you want to see them comment this line.

        # If no span in the file, still print the error
        print(f"error: {message}")
        return

def check_rust_test_errors(app, exception):
    """
    Sphinx 'build-finished' event handler that compiles the generated Rust file in test mode.

    This function is connected to the Sphinx build lifecycle and is executed after the build finishes.
    It invokes `rustc` in test mode on the generated Rust file and reports any compilation or test-related
    errors.

    Args:
        app: The Sphinx application object. Must have an `output_rust_file` attribute containing
             the path to the generated Rust source file.
        exception: Exception raised during the build process, or None if the build completed successfully.
    """
    rs_path = app.output_rust_file
    # Run the Rust compiler in test mode with JSON error output format.
    # capturing stdout and stderr as text.
    result = subprocess.run(
        ["rustc", "--test", "--edition=2024", "--error-format=json", "--emit=metadata", rs_path],
        # --emit=metadata or else rustc will produce a binary ./generated
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print("--- rustc Errors/Warnings ---")
        parse_rustc_json(result.stderr, app.output_rust_file)
        print("--- rustc Output ---")
        print(result.stdout)

    else:
        print("--- rustc Output  ---")
        print(result.stdout)
        if result.stderr: 
            print("\n\n--- rustc Warnings---")
            print(result.stderr)
