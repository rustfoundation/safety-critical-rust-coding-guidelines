from sphinx.errors import SphinxError
import logging
import re

logger = logging.getLogger('sphinx')
# reducing errors temporarly for dev
logger.setLevel(logging.ERROR) 

class ExecuteRustExamples(SphinxError):
    category = "ExecuteRustExamples Error"


def extract_code_blocks(text):
    pattern = re.compile(
        r"\.\. code-block:: rust\s*\n(?:(?:\s*\n)+)?((?: {2,}.*(?:\n|$))+)",
        re.MULTILINE
    )
    
    matches = pattern.findall(text)
    blocks = []
    for i, block in enumerate(matches):
        lines = block.splitlines()
        non_empty_lines = [line for line in lines if line.strip()]
        processed_block = "\n".join(non_empty_lines)
        blocks.append(processed_block)

        # print(f"====== code block {i + 1} ========")
        # print(processed_block)
        # print("====== end code block ========")

    return blocks

def strip_hidden(code_block):
    lines = code_block.splitlines()
    result = []
    hidden = []
    is_hidden = False

    for line in lines:
        stripped_for_marker_check = line[2:] if line.startswith("  ") else line 
        if "// HIDDEN START" in stripped_for_marker_check:
            is_hidden = True
            continue
        if "// HIDDEN END" in stripped_for_marker_check:
            is_hidden = False
            continue
        if not is_hidden:
            result.append(line)
        else:
            hidden.append(line)
    return "\n".join(result), "\n".join(hidden)

def remove_hidden_blocks_from_document(source_text):
    code_block_re = re.compile(
        r"(\.\. code-block:: rust\s*\n\n)((?: {2}.*\n)+)",
        re.DOTALL
    )
    # callback for replacing
    def replacer(match):
        prefix = match.group(1)  
        code_content = match.group(2)
        cleaned_code, hidden_code = strip_hidden(code_content)
        # print("============")
        # print(hidden_code)
        # print("============")
        return prefix + cleaned_code 

    modified_text = code_block_re.sub(replacer, source_text)
    return modified_text


def preprocess_rst_for_rust_code(app, docname, source):

    original_content = source[0]
    code_blocks = extract_code_blocks(original_content)
    modified_content = remove_hidden_blocks_from_document(original_content)
    source[0] = modified_content

    # print(f"Original content length: {len(original_content)}")
    # print(f"Extracted {len(code_blocks)} code blocks")

    safe_docname = docname.replace("/", "_").replace("-", "_")
    with open(app.output_rust_file, "a", encoding="utf-8") as f:
        for i, block in enumerate(code_blocks, start=1):
            f.write(f"// ==== Code Block {i} ====\n")
            f.write("#[test]\n")
            f.write(f"fn test_block_{safe_docname}_{i}() {{\n")
            for line in block.splitlines():
                f.write(f"    {line}\n") 
            f.write("}\n\n")
