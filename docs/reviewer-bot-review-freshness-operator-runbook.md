# Reviewer Bot Review Freshness Operator Runbook

## Purpose

This is the canonical operator runbook for reviewer-bot deferred-evidence freshness failures.

Until the rollout validation sections below are populated with repo-specific evidence, production rollout for approval-pending classification remains blocked by plan and unresolved waiting states must remain `observer_state_unknown`.

## Canonical Deferred-Gap Reasons

### `awaiting_observer_run`

- Wait through the configured discovery overlap and recheck window.
- Inspect whether a correlated observer run ever appeared for the exact `source_event_key`.
- Do not treat missing evidence as proof that the source event never happened.

### `awaiting_observer_approval`

- Review the PR and any workflow-file changes before approving the observer run.
- Do not approve blindly.
- If the run no longer matches the documented approval-pending signature in this runbook, treat that as implementation drift and fail closed.

### `observer_in_progress`

- Confirm that the correlated run is still active before rerunning anything.

### `observer_failed`

- Inspect the failed run and the artifact-upload step.
- Rerun only if trusted source-event correlation still matches.

### `observer_cancelled`

- Determine who or what cancelled the run before replaying.

### `observer_run_missing`

- Inspect workflow filters, repository Actions settings, and whether GitHub deleted an approval-pending run.
- Record the finding before rerunning anything.

### `observer_state_unknown`

- Inspect the raw run status and conclusion.
- Update implementation mapping only with a reviewed plan change.
- Do not guess manually.

### `artifact_missing`

- Inspect the completed observer run and artifact-upload behavior.
- Rerun only if the same trusted source-event correlation still matches.

### `artifact_invalid`

- Inspect the payload validation failure.
- Rerun only if the same trusted source-event correlation still matches.

### `artifact_expired`

- Do not reconstruct conversational freshness manually.
- Use repair or rectify only for conservative live-state repair allowed by plan.

### `reconcile_failed_closed`

- Inspect the exact validation failure.
- Rerun the trusted path only if the same source evidence still exists and still matches.

## Approval-Pending Validation Contract

The implementation may only classify `awaiting_observer_approval` from the exact workflow-run detail endpoint defined by plan.

Populate this section before production rollout:

- validation date:
- environment:
- event type:
- exact endpoint used: `GET /repos/{owner}/{repo}/actions/runs/{run_id}`
- exact accepted field/value signature:
- negative near-miss examples rejected by tests:
- validation run URL or run id:

If this section is incomplete, unresolved waiting states must remain `observer_state_unknown`.

## Observer Permission Validation Contract

Populate this section before production rollout:

- minimum working observer permissions: `contents: read`
- whether artifact upload required any explicit `actions` permission: not yet validated for this repo/org rollout; keep blocked until recorded here
- validation date:
- environment:
- validation run URL or run id:

If this section is incomplete, restricted observer rollout remains blocked by plan.

## Artifact Retention Contract

Record the effective retention window here before production rollout:

- configured retention: 7 days for reviewer-bot deferred artifacts in the shipped workflows
- higher-level cap, if any:
- validation date:

Do not emit `artifact_expired` unless prior visibility or documented retention proof exists as required by plan.

## Operator Notes

- Public-fork approval-pending runs may later disappear or be auto-deleted by GitHub.
- Missing runs are not proof that nothing happened.
- Operator-visible workflow summaries should point to this file path: `docs/reviewer-bot-review-freshness-operator-runbook.md`.
- Same-repo trusted-direct PR comment handling is limited to repo-associated `User` principals with `OWNER`, `MEMBER`, or `COLLABORATOR` association in the dedicated trusted workflow.
- Non-human automation PR comments, reviewer-bot self-comments, cross-repo PR comments, Dependabot PR comments, and all PR review freshness events stay deferred or ignored in this rollout.
