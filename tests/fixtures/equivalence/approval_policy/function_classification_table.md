Stays in `reviews.py`
- `resolve_pr_approval_state`
- `rebuild_pr_approval_state`
- `rebuild_pr_approval_state_result`
- `pr_has_current_write_approval`
- `apply_pr_approval_state`
- `trigger_mandatory_approver_escalation`
- `satisfy_mandatory_approver_requirement`
- `handle_pr_approved_review`

Moves to `approval_policy.py`
- `compute_pr_approval_state_result`
- `find_triage_approval_after`

Remains in `reviews_projection.py`
- `filter_current_head_reviews_for_cycle`
- `normalize_reviews_with_parsed_timestamps`
- `collect_permission_statuses`
- `compute_pr_approval_state_from_reviews`
- `desired_labels_from_response_state`

Out of scope
- `compute_reviewer_response_state`: out of scope for `C2a/C2b`
