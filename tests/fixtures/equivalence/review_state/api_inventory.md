Local-State-Only Mutation APIs
- ensure_review_entry: local-state-only mutation
- accept_channel_event: local-state-only mutation
- record_reviewer_activity: local-state-only mutation
- record_transition_notice_sent: local-state-only mutation
- set_current_reviewer: local-state-only mutation
- update_reviewer_activity: local-state-only mutation
- mark_review_complete: local-state-only mutation
- clear_transition_timers: local-state-only mutation

Live-Read-Assisted Mutation APIs
- accept_reviewer_review_from_live_review: live-read-assisted mutation; C1c in-scope
- refresh_reviewer_review_from_live_preferred_review: live-read-assisted mutation; C1c in-scope
- repair_missing_reviewer_review_state: live-read-assisted mutation; C1c in-scope

Read-Only Helpers
- get_current_cycle_boundary: read-only helper
- list_open_tracked_review_items: read-only helper
- semantic_key_seen: read-only helper
