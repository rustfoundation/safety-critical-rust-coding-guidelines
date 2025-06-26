from . import rust_examples_aggregate 
from . import rustc 
import os

def setup(app):

    app.output_rust_file = "build/rust-code-blocks/generated.rs"

    # create build dir 
    if not os.path.exists("build/rust-code-blocks"):
        os.makedirs("build/rust-code-blocks")
    if os.path.isfile(app.output_rust_file):
        with open(app.output_rust_file, 'w'):
            pass  

    # we hook into 'source-read' because data is mutable at this point and easier to parse 
    # and it also makes this extension indepandant from `needs`.
    #
    app.connect('source-read', rust_examples_aggregate.preprocess_rst_for_rust_code)

    if app.config.test_rust_blocks:
        app.connect('build-finished', rustc.check_rust_test_errors)
    return {
        'version': '0.1',
        'parallel_read_safe': False,
    }
