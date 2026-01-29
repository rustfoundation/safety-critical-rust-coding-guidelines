# FLS Audit Guide

This guide explains how to audit differences between `src/spec.lock` and the
current Ferrocene Language Specification (FLS).

## Quick start

```shell
uv run python scripts/fls_audit.py --summary-only
uv run python scripts/fls_audit.py
```

## What the audit does

- Compares `src/spec.lock` against the live FLS paragraph IDs.
- Groups changes into added/removed/modified/renumbered-only/header changes.
- Highlights potential guideline impact and structural reordering.

## Outputs

- `build/fls_audit/report.json`
- `build/fls_audit/report.md`

## Baseline and current selection

By default, the audit uses:

- Baseline: `metadata.fls_deployed_commit` from `src/spec.lock` (if present).
- Current: latest GitHub Pages deployment commit.

You can override with explicit commits:

```shell
uv run python scripts/fls_audit.py --baseline-fls-commit <sha> --current-fls-commit <sha>
```

Or use deployment offsets (relative to the latest deployment):

```shell
uv run python scripts/fls_audit.py --baseline-deployment-offset 2
uv run python scripts/fls_audit.py --current-deployment-offset 1
```

## Snapshot workflows (text diffs)

Create a snapshot of the current FLS text:

```shell
uv run python scripts/fls_audit.py --write-text-snapshot build/fls_audit/snapshots
```

Compare against a prior snapshot:

```shell
uv run python scripts/fls_audit.py --baseline-text-snapshot build/fls_audit/snapshots/<snapshot>.json
```

## Offline audit

```shell
uv run python scripts/fls_audit.py --snapshot path/to/paragraph-ids.json
```

## Heuristics and legacy output

- Include heuristic match details:

```shell
uv run python scripts/fls_audit.py --include-heuristic-details
```

- Append the legacy diff section:

```shell
uv run python scripts/fls_audit.py --include-legacy-report
```

## Cache

The FLS repo is cached under `./.cache/fls-audit/` and is safe to delete.

## Rationalization checklist

1. Check if any guidelines are affected. If none, go to step 6.
2. For each affected guideline, audit the previous and current text of the
   referenced FLS paragraph.
3. If the prior and new text do not affect the guideline, continue to the next
   affected guideline.
4. If the text change affects the guideline, update the guideline to match the
   new FLS text.
5. Repeat until all affected guidelines are handled.
6. Done.

After completing the checklist, update the local `spec.lock`:

```shell
./make.py --update-spec-lock-file
```

Open a new PR with only the changes needed to rationalize the guidelines with
the updated FLS text.
