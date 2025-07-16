from . import rust_examples_aggregate 
from . import rustc 
import os
from pathlib import Path

def setup(app):


    # Define output directory
    app.output_rust = "build/rust-code-blocks/"

    # Ensure the src directory exists
    base_dir = Path(app.output_rust)
    src_dir = base_dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)


    # Write Cargo.toml with required dependencies
    cargo_toml = base_dir / "Cargo.toml"
    cargo_toml.write_text(
        """[package]
name = "sc_generated_tests"
version = "0.1.0"
edition = "2024"

[dependencies]
 # tokio = { version = "1", features = ["macros", "rt-multi-thread"] }
""",
        encoding="utf-8",
    )


    print(f"Setup complete in '{base_dir.resolve()}'")

    # we hook into 'source-read' because data is mutable at this point and easier to parse 
    # and it also makes this extension indepandant from `needs`.
    if not app.config.test_rust_blocks:
        # empty lib.rs on every run (incremental build is not supported)
        with open(app.output_rust + "src/lib.rs", "w", encoding="utf-8"):
            pass
        app.connect('source-read', rust_examples_aggregate.preprocess_rst_for_rust_code)
    else:
        app.connect('build-finished', rustc.check_rust_test_errors)

    return {
        'version': '0.1',
        'parallel_read_safe': False,
        'parallel_write_safe': False,
    }
