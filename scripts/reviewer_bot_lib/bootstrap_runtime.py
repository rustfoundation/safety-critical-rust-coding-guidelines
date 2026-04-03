"""Bootstrap runtime composition for the reviewer-bot entrypoint."""

from __future__ import annotations

from types import SimpleNamespace

from . import (
    automation,
    commands,
    comment_routing,
    config,
    events,
    github_api,
    lease_lock,
    lifecycle,
    maintenance,
    reconcile,
    review_state,
    reviews,
    state_store,
)
from .queue import (
    get_next_reviewer,
    process_pass_until_expirations,
    record_assignment,
    reposition_member_as_next,
    sync_members_with_queue,
)
from .runtime import ReviewerBotRuntime


def build_runtime(*, requests, sys, random, time, active_lease_context=None) -> ReviewerBotRuntime:
    runtime: ReviewerBotRuntime | None = None

    state_store_services = SimpleNamespace(
        load_state=lambda *, fail_on_unavailable=False: state_store.load_state(
            runtime, fail_on_unavailable=fail_on_unavailable
        ),
        save_state=lambda current_state: state_store.save_state(runtime, current_state),
    )
    github_services = SimpleNamespace(
        github_api_request=lambda *args, **kwargs: github_api.github_api_request(
            runtime, *args, **kwargs
        ),
        github_api=lambda *args, **kwargs: github_api.github_api(runtime, *args, **kwargs),
    )
    lock_services = SimpleNamespace()
    handlers = SimpleNamespace(
        handle_issue_or_pr_opened=lambda current_state: lifecycle.handle_issue_or_pr_opened(runtime, current_state),
        handle_labeled_event=lambda current_state: lifecycle.handle_labeled_event(runtime, current_state),
        handle_issue_edited_event=lambda current_state: lifecycle.handle_issue_edited_event(runtime, current_state),
        handle_closed_event=lambda current_state: lifecycle.handle_closed_event(runtime, current_state),
        handle_pull_request_target_synchronize=lambda current_state: lifecycle.handle_pull_request_target_synchronize(
            runtime, current_state
        ),
        handle_pull_request_review_event=lambda current_state: events.handle_pull_request_review_event(runtime, current_state),
        handle_comment_event=lambda current_state: comment_routing.handle_comment_event(runtime, current_state),
        handle_manual_dispatch=lambda current_state: maintenance.handle_manual_dispatch(runtime, current_state),
        handle_scheduled_check=lambda current_state: maintenance.handle_scheduled_check(runtime, current_state),
        handle_workflow_run_event=lambda current_state: reconcile.handle_workflow_run_event(runtime, current_state),
    )
    adapters = SimpleNamespace(
        assert_lock_held=lambda context: state_store.assert_lock_held(runtime, context),
        get_github_token=github_api.get_github_token,
        get_github_graphql_token=lambda *, prefer_board_token=False: github_api.get_github_graphql_token(
            runtime, prefer_board_token=prefer_board_token
        ),
        github_graphql=lambda query, variables=None, *, token=None: github_api.github_graphql(
            runtime, query, variables, token=token
        ),
        post_comment=lambda issue_number, body: github_api.post_comment(runtime, issue_number, body),
        get_repo_labels=lambda: github_api.get_repo_labels(runtime),
        add_label=lambda issue_number, label: github_api.add_label(runtime, issue_number, label),
        remove_label=lambda issue_number, label: github_api.remove_label(runtime, issue_number, label),
        ensure_label_exists=lambda label, *, color=None, description=None: github_api.ensure_label_exists(
            runtime, label, color=color, description=description
        ),
        get_issue_assignees=lambda issue_number: github_api.get_issue_assignees(runtime, issue_number),
        request_reviewer_assignment=lambda issue_number, username: github_api.request_reviewer_assignment(
            runtime, issue_number, username
        ),
        get_assignment_failure_comment=lambda reviewer, attempt: github_api.get_assignment_failure_comment(
            runtime, reviewer, attempt
        ),
        add_reaction=lambda comment_id, reaction: github_api.add_reaction(runtime, comment_id, reaction),
        remove_assignee=lambda issue_number, username: github_api.remove_assignee(runtime, issue_number, username),
        remove_pr_reviewer=lambda issue_number, username: github_api.remove_pr_reviewer(runtime, issue_number, username),
        unassign_reviewer=lambda issue_number, username: github_api.unassign_reviewer(runtime, issue_number, username),
        get_user_permission_status=lambda username, required_permission="triage": github_api.get_user_permission_status(
            runtime, username, required_permission
        ),
        check_user_permission=lambda username, required_permission="triage": github_api.check_user_permission(
            runtime, username, required_permission
        ),
        get_issue_or_pr_snapshot=lambda issue_number: github_api.github_api(runtime, "GET", f"issues/{issue_number}"),
        get_pull_request_reviews=lambda issue_number: reviews.get_pull_request_reviews(runtime, issue_number),
        maybe_record_head_observation_repair=lambda issue_number, review_data: lifecycle.maybe_record_head_observation_repair(
            runtime, issue_number, review_data
        ),
        handle_transition_notice=lambda current_state, issue_number, reviewer: lifecycle.handle_transition_notice(
            runtime, current_state, issue_number, reviewer
        ),
        handle_pass_command=lambda current_state, issue_number, comment_author, reason, request=None: commands.handle_pass_command(
            runtime, current_state, issue_number, comment_author, reason, request=request
        ),
        handle_pass_until_command=lambda current_state, issue_number, comment_author, return_date, reason, request=None: commands.handle_pass_until_command(
            runtime, current_state, issue_number, comment_author, return_date, reason, request=request
        ),
        handle_label_command=lambda current_state, issue_number, label_string, request=None: commands.handle_label_command(
            runtime, current_state, issue_number, label_string, request=request
        ),
        handle_sync_members_command=lambda current_state: commands.handle_sync_members_command(
            runtime, current_state
        ),
        handle_queue_command=lambda current_state: commands.handle_queue_command(runtime, current_state),
        handle_commands_command=lambda: commands.handle_commands_command(runtime),
        handle_claim_command=lambda current_state, issue_number, comment_author, request=None: commands.handle_claim_command(
            runtime, current_state, issue_number, comment_author, request=request
        ),
        handle_release_command=lambda current_state, issue_number, comment_author, args=None, request=None: commands.handle_release_command(
            runtime, current_state, issue_number, comment_author, args, request=request
        ),
        handle_rectify_command=lambda current_state, issue_number, comment_author: reconcile.handle_rectify_command(
            runtime, current_state, issue_number, comment_author
        ),
        handle_assign_command=lambda current_state, issue_number, username, request=None: commands.handle_assign_command(
            runtime, current_state, issue_number, username, request=request
        ),
        handle_assign_from_queue_command=lambda current_state, issue_number, request=None: commands.handle_assign_from_queue_command(
            runtime, current_state, issue_number, request=request
        ),
        handle_accept_no_fls_changes_command=lambda issue_number, comment_author: automation.handle_accept_no_fls_changes_command(
            runtime, issue_number, comment_author
        ),
        get_commands_help=config.get_commands_help,
        ensure_review_entry=lambda current_state, issue_number, create=False: review_state.ensure_review_entry(
            current_state, issue_number, create=create
        ),
        set_current_reviewer=lambda current_state, issue_number, reviewer, assignment_method="round-robin": review_state.set_current_reviewer(
            current_state, issue_number, reviewer, assignment_method=assignment_method
        ),
        update_reviewer_activity=lambda current_state, issue_number, reviewer: review_state.update_reviewer_activity(
            current_state, issue_number, reviewer
        ),
        mark_review_complete=lambda current_state, issue_number, reviewer, source: review_state.mark_review_complete(
            current_state, issue_number, reviewer, source
        ),
        is_triage_or_higher=lambda username: reviews.is_triage_or_higher(runtime, username),
        trigger_mandatory_approver_escalation=lambda current_state, issue_number: reviews.trigger_mandatory_approver_escalation(
            runtime, current_state, issue_number
        ),
        satisfy_mandatory_approver_requirement=lambda current_state, issue_number, approver: reviews.satisfy_mandatory_approver_requirement(
            runtime, current_state, issue_number, approver
        ),
        get_next_reviewer=get_next_reviewer,
        strip_code_blocks=commands.strip_code_blocks,
        parse_command=lambda comment_body: commands.parse_command(runtime, comment_body),
        record_assignment=record_assignment,
        reposition_member_as_next=reposition_member_as_next,
        process_pass_until_expirations=process_pass_until_expirations,
        sync_members_with_queue=lambda current_state: sync_members_with_queue(runtime, current_state),
        parse_iso8601_timestamp=state_store.parse_iso8601_timestamp,
        compute_reviewer_response_state=lambda issue_number, review_data, *, issue_snapshot=None: reviews.compute_reviewer_response_state(
            runtime, issue_number, review_data, issue_snapshot=issue_snapshot
        ),
        sync_status_labels_for_items=lambda current_state, issue_numbers: reviews.sync_status_labels_for_items(
            runtime, current_state, issue_numbers
        ),
        run_command=automation.run_command,
        summarize_output=automation.summarize_output,
        list_changed_files=automation.list_changed_files,
        get_default_branch=lambda: automation.get_default_branch(runtime),
        find_open_pr_for_branch_status=lambda branch: automation.find_open_pr_for_branch_status(runtime, branch),
        create_pull_request=lambda branch, base, issue_number: automation.create_pull_request(
            runtime, branch, base, issue_number
        ),
        parse_issue_labels=automation.bot_parse_issue_labels,
        normalize_lock_metadata=state_store.normalize_lock_metadata,
        get_state_issue=lambda: state_store.get_state_issue(runtime),
        clear_lock_metadata=lambda: lease_lock.clear_lock_metadata(runtime),
        get_state_issue_snapshot=lambda: state_store.get_state_issue_snapshot(runtime),
        conditional_patch_state_issue=lambda body, etag=None: state_store.conditional_patch_state_issue(
            runtime, body, etag
        ),
        parse_lock_metadata_from_issue_body=state_store.parse_lock_metadata_from_issue_body,
        render_state_issue_body=lambda current_state, lock_meta, base_body=None, *, preserve_state_block=False: state_store.render_state_issue_body(
            current_state,
            lock_meta,
            base_body,
            preserve_state_block=preserve_state_block,
        ),
        get_state_issue_html_url=lambda: lease_lock.get_state_issue_html_url(runtime),
        get_lock_ref_display=lambda: lease_lock.get_lock_ref_display(runtime),
        get_lock_ref_snapshot=lambda: lease_lock.get_lock_ref_snapshot(runtime),
        build_lock_metadata=lambda *args, **kwargs: lease_lock.build_lock_metadata(runtime, *args, **kwargs),
        create_lock_commit=lambda parent_sha, tree_sha, lock_meta: lease_lock.create_lock_commit(
            runtime, parent_sha, tree_sha, lock_meta
        ),
        cas_update_lock_ref=lambda new_sha: lease_lock.cas_update_lock_ref(runtime, new_sha),
        lock_is_currently_valid=lambda lock_meta, now=None: lease_lock.lock_is_currently_valid(runtime, lock_meta, now),
        renew_state_issue_lease_lock=lambda context: lease_lock.renew_state_issue_lease_lock(runtime, context),
        ensure_state_issue_lease_lock_fresh=lambda: lease_lock.ensure_state_issue_lease_lock_fresh(runtime),
        acquire_state_issue_lease_lock=lambda: lease_lock.acquire_state_issue_lease_lock(runtime),
        release_state_issue_lease_lock=lambda: lease_lock.release_state_issue_lease_lock(runtime),
        get_active_lease_context=lambda: runtime.ACTIVE_LEASE_CONTEXT,
    )

    runtime = ReviewerBotRuntime(
        requests=requests,
        sys=sys,
        random=random,
        time=time,
        state_store=state_store_services,
        github=github_services,
        locks=lock_services,
        handlers=handlers,
        adapters=adapters,
        active_lease_context=active_lease_context,
    )
    return runtime
