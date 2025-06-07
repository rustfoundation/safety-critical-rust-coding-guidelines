import json
import re
import random 
import string


def generate_id(prefix):
    """
    Generate a random ID with the given prefix.
    """

    CHARS = string.ascii_letters + string.digits
    ID_LENGTH = 12
    random_part = "".join(random.choice(CHARS) for _ in range(ID_LENGTH))
    return f"{prefix}_{random_part}"

def extract_form_fields(issue_body: str) -> dict:
    """
    This function parses issues json into a dict of important fields
    """
    # Mapping from issue body headers to dict keys
    # Changing issues fields name to snake_case (eg. 'Guideline Title' => 'guideline_title')
    header_map = {
        "Chapter": "chapter",
        "Guideline Title": "guideline_title",
        "Category": "category",
        "Status": "status",
        "Release Begin": "release_begin",
        "Release End": "release_end",
        "FLS Paragraph ID": "fls_id",
        "Decidability": "decidability",
        "Scope": "scope",
        "Tags": "tags",
        "Amplification": "amplification",
        "Exception(s)": "exceptions",
        "Rationale": "rationale",
        "Non-Compliant Example - Prose": "non_compliant_ex_prose",
        "Non-Compliant Example - Code": "non_compliant_ex",
        "Compliant Example - Prose": "compliant_example_prose",
        "Compliant Example - Code": "compliant_example",
    }

    fields = {v: "" for v in header_map.values()}

    lines = issue_body.splitlines()
    current_key = None
    current_value_lines = []

    lines.append("### END")  # Sentinel to process last field

    # Look for '###' in every line, ### represent a sections/field in a guideline
    for line in lines:
        header_match = re.match(r'^### (.+)$', line.strip())
        if header_match:
            # Save previous field value if any
            if current_key is not None:
                value = "\n".join(current_value_lines).strip()
                # `_No response_` represents an empty field
                if value == "_No response_":
                    value = ""
                if current_key in fields:
                    fields[current_key] = value

            header = header_match.group(1).strip()
            current_key = header_map.get(header)  # Map to dict key or None if unknown
            current_value_lines = []
        else:
            current_value_lines.append(line)

    return fields

def save_guideline_file(content: str, chapter: str):
    """
    Appends a guideline str to a chapter

    """
    content = "\n" + content + "\n"
    # os.makedirs(f"src/coding-guidelines/{chapter}", exist_ok=True)
    filename = f"src/coding-guidelines/{chapter.lower()}.rst"

    # for testing in the GA summary 
    print("=====CONTENT=====")
    print(content)
    print("=====CONTENT=END=====")

    with open(filename, 'a', encoding='utf-8') as f:
        f.write(content)
    print(f"Saved guideline to {filename}")

def guideline_template(fields: dict) -> str:
    """
    This function turns a dictionary that contains the guideline fields 
    into a proper .rst guideline format
    """
    

    # taken from generate-guideline-templates.py
    # to generate random ids
    guideline_id = generate_id("gui")
    rationale_id = generate_id("rat")
    non_compliant_example_id = generate_id("non_compl_ex")
    compliant_example_id = generate_id("compl_ex")

    def get(key):
        return fields.get(key, "").strip()


    guideline_text = f""".. guideline:: {get('guideline_title')}
   :id: {guideline_id} 
   :category: {get('category').lower()}
   :status: {get('status').lower()}
   :release: {get('release_begin').lower()}-{get('release_end')}
   :fls: {get('fls_id').lower()}
   :decidability: {get('decidability').lower()}
   :scope: {get('scope').lower()}
   :tags: {",".join(get('tags').split(" "))}

   {get('amplification')}

   .. rationale:: 
      :id: {rationale_id} 
      :status: {get('status').lower()}

      {get('rationale')}

   .. non_compliant_example::
      :id: {non_compliant_example_id} 
      :status: {get('status').lower()}

      {get('non_compliant_ex_prose')}
   
      .. code-block:: rust
   
        {get('non_compliant_example')}

   .. compliant_example::
      :id: {compliant_example_id} 
      :status: {get('status').lower()}

      {get('compliant_example_prose')}
   
      .. code-block:: rust
   
        {get('compliant_example')}
"""

    return guideline_text

import sys
if __name__ == "__main__":
    # for testing purposes pull an issue in json format 
    # eg https://api.github.com/repos/x0rw/safety-critical-rust-coding-guidelines/issues/4
    # this json is how the issue is visible to the GA bot
    #
    # with open('scripts/issue_sample.json', 'r', encoding='utf-8') as f:
    #     issue = json.load(f)
    #

    ## locally test with `cat scripts/test_issue_sample.json | python3 scripts/auto-pr-helper.py`

    # Read json from stdin
    issue_json = sys.stdin.read()
    issue = json.loads(issue_json)

    issue_number = issue['number']
    issue_title = issue['title']
    issue_body = issue['body']

    fields = extract_form_fields(issue_body)
    chapter = fields["chapter"]


    content = guideline_template(fields)


    save_guideline_file(content, chapter)


