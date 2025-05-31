import json
import re
import random 
import string

CHARS = string.ascii_letters + string.digits
ID_LENGTH = 12

def generate_id(prefix):
    """Generate a random ID with the given prefix."""
    random_part = "".join(random.choice(CHARS) for _ in range(ID_LENGTH))
    return f"{prefix}_{random_part}"

def extract_form_fields(issue_body: str) -> dict:
    # Mapping from issue body headers to dict keys
    header_map = {
        "Chapter": "Chapter",
        "Guideline Title": "Guideline Title",
        "Category": "Category",
        "Status": "Status",
        "Release Begin": "Release Begin",
        "Release End": "Release End",
        "FLS Paragraph ID": "Fls Paragraph Id",
        "Decidability": "Decidability",
        "Scope": "Scope",
        "Tags": "Tags",
        "Amplification": "Amplification",
        "Exception(s)": "Exception(S)",
        "Rationale": "Rationale",
        "Non-Compliant Example - Prose": "Non Compliant Example   Prose",
        "Non-Compliant Example - Code": "Non Compliant Example   Code",
        "Compliant Example - Prose": "Compliant Example   Prose",
        "Compliant Example - Code": "Compliant Example   Code",
    }

    fields = {v: "" for v in header_map.values()}

    lines = issue_body.splitlines()
    current_key = None
    current_value_lines = []

    lines.append("### END")  # Sentinel to process last field

    for line in lines:
        header_match = re.match(r'^### (.+)$', line.strip())
        if header_match:
            # Save previous field value if any
            if current_key is not None:
                value = "\n".join(current_value_lines).strip()
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

    # taken from generate-guideline-templates.py
    guideline_id = generate_id("gui")
    rationale_id = generate_id("rat")
    non_compliant_example_id = generate_id("non_compl_ex")
    compliant_example_id = generate_id("compl_ex")

    def get(key):
        return fields.get(key, "").strip()


    guideline_text = f""".. guideline:: {get('Guideline Title')}
   :id: {guideline_id} 
   :category: {get('Category').lower()}
   :status: {get('Status').lower()}
   :release: {get('Release Begin').lower()}
   :fls: {get('Fls Paragraph Id').lower()}
   :decidability: {get('Decidability').lower()}
   :scope: {get('Scope').lower()}
   :tags: {",".join(get('Tags').split(" "))}

   {get('Amplification')}

   .. rationale:: 
      :id: {rationale_id} 
      :status: {get('Status').lower()}

      {get('Rationale')}

   .. non_compliant_example::
      :id: {non_compliant_example_id} 
      :status: {get('Status').lower()}

      {get('Non Compliant Example   Prose')}
   
      .. code-block:: rust
   
        {get('Non Compliant Example   Code')}

   .. compliant_example::
      :id: {compliant_example_id} 
      :status: {get('Status').lower()}

      {get('Compliant Example   Prose')}
   
      .. code-block:: rust
   
        {get('Compliant Example   Code')}
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

    issue_json = sys.stdin.read()
    issue = json.loads(issue_json)

    issue_number = issue['number']
    issue_title = issue['title']
    issue_body = issue['body']

    fields = extract_form_fields(issue_body)
    chapter = fields["Chapter"]


    content = guideline_template(fields)


    save_guideline_file(content, chapter)


