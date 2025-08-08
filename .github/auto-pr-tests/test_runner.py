import difflib
import re
import subprocess
from pathlib import Path


def normalize_ids(text: str) -> str:
    return re.sub(r"(:id:\s+[a-z_]+)_[a-zA-Z0-9]+", r"\1_IGNORED_ID", text)


def compare(issue_json_path: Path, snapshot_path: Path) -> bool:
    input_json = issue_json_path.read_text()

    result = subprocess.run(
        ["uv", "run", "python", "scripts/auto-pr-helper.py"],
        input=input_json.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=True,
    )

    # Normalize the actual output and the snapshot, this is crucial in snapshot tests to
    # ignore random/volatile values.
    actual_output = normalize_ids(result.stdout.decode())
    expected_output = normalize_ids(snapshot_path.read_text())

    # Compare
    if actual_output != expected_output:
        diff = difflib.unified_diff(
            expected_output.splitlines(),
            actual_output.splitlines(),
            fromfile=str(snapshot_path),
            tofile="generated",
            lineterm="",
        )
        print(f"Difference found in {issue_json_path.name}:")
        print("\n".join(diff))
        return False
    else:
        print(f"{issue_json_path.name} matches snapshot.")
        return True


# to generate snapshot:
# create or change the test_issue_xx file and then use this command after replacing XX with your test number:
## `cat .github/auto-pr-tests/test_issue_XX.json | uv run python scripts/auto-pr-helper.py 2&>/dev/null > .github/auto-pr-tests/test_issue_0XX.snapshot`
tests = {
    "test_01": (
        Path(".github/auto-pr-tests/test_issue_01.json"),
        Path(".github/auto-pr-tests/test_issue_01.snapshot"),
    ),
    "test_02": (
        Path(".github/auto-pr-tests/test_issue_02.json"),
        Path(".github/auto-pr-tests/test_issue_02.snapshot"),
    ),
    "test_03": (
        Path(".github/auto-pr-tests/test_issue_03.json"),
        Path(".github/auto-pr-tests/test_issue_03.snapshot"),
    ),
}

# Run all tests
all_passed = True
for name, (issue_json, snapshot) in tests.items():
    if not compare(issue_json, snapshot):
        all_passed = False

if not all_passed:
    exit(1)
