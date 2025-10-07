## How to Add and Document Tests in `auto-pr-tests`

The test script `scripts/auto-pr-helper.py` transforms an issue from JSON format into our `.rst` format.

This directory contains test issue files in JSON format along with their expected output snapshots. These tests are executed by the script `test_runner.py`.

### Adding a New Test

1. **Create Input JSON File**  

   First, obtain the JSON data for the GitHub issue you want to use as a test case. Name the file test_issue_XX.json, where XX is a number, Instructions on how to get this JSON data are provided in the next section.

2. **Generate Expected Output Snapshot**  
   Run the following command to generate the corresponding `.snapshot` file automatically:

   ```bash
   cat .github/auto-pr-tests/test_issue_XX.json | uv run scripts/auto-pr-helper.py > .github/auto-pr-tests/test_issue_XX.snapshot
   ```
   It is better to run this command and manually verify the output, rather than creating the snapshot manually.
3. **Add Test to the Test List**
   Add your new JSON and snapshot file paths to the tests dictionary inside test_runner.py(line 47). This registers the new test so it will be run.
4. Run Tests
   Execute test_runner.py to verify that the output matches the expected snapshots.


### How to Get Issue JSON from GitHub API

To create the input JSON file (`test_issue_XX.json`), you can fetch the issue data directly from the GitHub API:

1. Find the issue number and repository where the issue is located.

2. Use a tool like `curl` or any HTTP client to request the issue JSON data:

```bash
curl https://api.github.com/repos/OWNER/REPO/issues/ISSUE_NUMBER > test_issue_XX.json
```
