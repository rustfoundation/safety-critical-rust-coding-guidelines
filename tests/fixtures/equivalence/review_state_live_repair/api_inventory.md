Live-Read-Assisted Review Repair APIs
- accept_reviewer_review_from_live_review: accepts a matching current-reviewer live review into reviewer_review channel state
- refresh_reviewer_review_from_live_preferred_review: refreshes stored reviewer_review state from the preferred live review for the active cycle
- repair_missing_reviewer_review_state: delegates repair through the same preferred live review refresh path

Exact Frozen Scenarios
- matching current reviewer and valid submitted review
- reviewer mismatch
- no preferred review found
- head repair without review acceptance
- no-op repair path

Out Of Scope For G2a
- ensure_review_entry
- accept_channel_event
- record_reviewer_activity
- set_current_reviewer
- mark_review_complete
