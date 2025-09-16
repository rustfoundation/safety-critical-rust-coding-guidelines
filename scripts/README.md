# Scripts for automating processes around the coding guidelines

## `auto-pr-helper.py`

This script is a utility for automating the generation of guidelines. It takes a GitHub issue's JSON data from standard input, parses its body (which is expected to follow a specific issue template), and converts it into a formatted reStructuredText (`.rst`) guideline.

---

### How to Use

The script reads a JSON payload from **standard input**. The most common way to provide this input is by using a pipe (`|`) to feed the output of another command into the script.

#### 1. Using a Local JSON File

For local testing, you can use `cat` to pipe the contents of a saved GitHub issue JSON file into the script.

```bash
cat path/to/your_issue.json | uv run scripts/auto-pr-helper.py
```

#### 2. Fetching from the GitHub API directly

You can fetch the data for a live issue directly from the GitHub API using curl and pipe it to the script. This is useful for getting the most up-to-date content.

```bash
curl https://api.github.com/repos/rustfoundation/safety-critical-rust-coding-guidelines/issues/156 | uv run ./scripts/auto-pr-helper.py
```

## `markdown_to_github_issue.py`

### How to use

You need to create a personal access token for the target repository as [described here](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#creating-a-fine-grained-personal-access-token).
Make sure the "Issues" permission is granted as "read and write" for the token.

Pass the token to the tool via the `--auth-token` command line parameter.
