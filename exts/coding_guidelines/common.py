import logging
import re
from typing import Dict, List, Tuple

from tqdm import tqdm

# This is a wrapper around tqdm that allows us to disable it with this global variable
disable_tqdm = False


def get_tqdm(**kwargs):
    kwargs["disable"] = disable_tqdm
    return tqdm(**kwargs)


def sanitize_directive_content(content: str) -> Tuple[str, Dict[str, str], List[str]]:
    """
    Detect and extract RST directive options incorrectly included in code content.
    
    This handles cases where indentation issues in RST source files cause Sphinx's
    directive parser to not recognize directive options, resulting in them appearing
    in self.content instead of self.options.
    
    For example, if the RST has:
        .. rust-example::
            :version: 1.79
            
           use std::num::NonZero;  # <- Less indented than option!
    
    Sphinx will put ":version: 1.79" in content instead of options.
    
    Args:
        content: The raw code content from a directive (joined self.content)
        
    Returns:
        Tuple of (sanitized_code, extracted_options, raw_option_lines)
        - sanitized_code: Code with option-like lines removed from the start
        - extracted_options: Dict mapping option names to values
        - raw_option_lines: The original lines that were extracted (for error messages)
    """
    lines = content.split('\n')
    extracted_options: Dict[str, str] = {}
    raw_option_lines: List[str] = []
    code_start_idx = 0
    
    # Pattern to match directive options: :option_name: optional_value
    # This matches the same format Sphinx expects for directive options
    option_pattern = re.compile(r'^:(\w+):\s*(.*)$')
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Skip blank lines at the start (between options and code)
        if not stripped:
            code_start_idx = i + 1
            continue
        
        # Check if this looks like a directive option
        match = option_pattern.match(stripped)
        if match:
            opt_name = match.group(1)
            opt_value = match.group(2).strip()
            extracted_options[opt_name] = opt_value
            raw_option_lines.append(stripped)
            code_start_idx = i + 1
        else:
            # First non-option, non-blank line - actual code starts here
            break
    
    sanitized_code = '\n'.join(lines[code_start_idx:])
    return sanitized_code, extracted_options, raw_option_lines


# Get the Sphinx logger
logger = logging.getLogger("sphinx")
logger.setLevel(logging.WARNING)

# This is what controls the progress bar format
bar_format = "{l_bar}{bar}| {n_fmt}/{total_fmt} {postfix}"
