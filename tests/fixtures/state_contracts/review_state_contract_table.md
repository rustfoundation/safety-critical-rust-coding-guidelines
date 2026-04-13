Top-Level Persisted Keys
- active_reviews: required
- schema_version: required
- freshness_runtime_epoch: required
- projection epoch markers: intentionally not frozen
- status_projection_epoch: lazily materialized
- last_updated: intentionally not frozen
- current_index: required
- queue: required
- pass_until: required
- recent_assignments: required

Per-Review-Entry Keys
- skipped: tolerated legacy shape
- current_reviewer: lazily materialized
- cycle_started_at: lazily materialized
- active_cycle_started_at: lazily materialized
- assigned_at: lazily materialized
- active_head_sha: lazily materialized
- last_reviewer_activity: lazily materialized
- transition_warning_sent: lazily materialized
- transition_notice_sent_at: lazily materialized
- assignment_method: lazily materialized
- review_completed_at: lazily materialized
- review_completed_by: lazily materialized
- review_completion_source: lazily materialized
- mandatory_approver_required: lazily materialized
- mandatory_approver_label_applied_at: lazily materialized
- mandatory_approver_pinged_at: lazily materialized
- mandatory_approver_satisfied_by: lazily materialized
- mandatory_approver_satisfied_at: lazily materialized
- sidecars: lazily materialized
- repair_markers: nested under sidecars with fixed owner keys
- overdue_anchor: lazily materialized
- deferred_gaps: nested under sidecars
- observer_discovery_watermarks: nested under sidecars
- pending_privileged_commands: nested under sidecars
- current_cycle_completion: lazily materialized
- current_cycle_write_approval: lazily materialized
- reconciled_source_events: nested under sidecars as a map; tolerated legacy list shape

Per-Channel Keys
- accepted: lazily materialized
- seen_keys: tolerated legacy shape

Lazy-Upgrade Cases
- missing active_reviews: tolerated legacy shape
- list-form review entry converted to {"skipped": ...}: tolerated legacy shape
- missing channel maps: lazily materialized
- missing sidecar-backed fields: lazily materialized
- non-list reconciled_source_events: tolerated legacy shape
- non-list skipped: tolerated legacy shape
