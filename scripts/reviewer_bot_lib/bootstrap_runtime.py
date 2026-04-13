"""Bootstrap runtime composition for the reviewer-bot entrypoint."""

from __future__ import annotations

from . import (
    automation,
    commands,
    comment_routing,
    config,
    github_api,
    lease_lock,
    lifecycle,
    maintenance,
    members,
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
from .runtime import (
    ReviewerBotRuntime,
    _EnvConfig,
    _FileOutputSink,
    _JsonDeferredPayloadLoader,
)


class _BootstrapStateStoreServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def load_state(self, *, fail_on_unavailable: bool = False):
        return state_store.load_state(self._runtime_getter(), fail_on_unavailable=fail_on_unavailable)

    def save_state(self, current_state):
        return state_store.save_state(self._runtime_getter(), current_state)


class _BootstrapGitHubServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def github_api_request(self, *args, **kwargs):
        return github_api.github_api_request(self._runtime_getter(), *args, **kwargs)

    def github_api(self, *args, **kwargs):
        return github_api.github_api(self._runtime_getter(), *args, **kwargs)

    def github_graphql_request(self, *args, **kwargs):
        return github_api.github_graphql_request(self._runtime_getter(), *args, **kwargs)

    def get_github_token(self):
        return github_api.get_github_token(self._runtime_getter())

    def get_github_graphql_token(self, *, prefer_board_token=False):
        return github_api.get_github_graphql_token(self._runtime_getter(), prefer_board_token=prefer_board_token)

    def github_graphql(self, query, variables=None, *, token=None):
        return github_api.github_graphql(self._runtime_getter(), query, variables, token=token)

    def post_comment(self, issue_number, body):
        return github_api.post_comment(self._runtime_getter(), issue_number, body)

    def get_repo_labels(self):
        return github_api.get_repo_labels(self._runtime_getter())

    def add_label(self, issue_number, label):
        return github_api.add_label(self._runtime_getter(), issue_number, label)

    def remove_label(self, issue_number, label):
        return github_api.remove_label(self._runtime_getter(), issue_number, label)

    def ensure_label_exists(self, label, *, color=None, description=None):
        return github_api.ensure_label_exists(self._runtime_getter(), label, color=color, description=description)

    def get_issue_assignees(self, issue_number):
        return github_api.get_issue_assignees(self._runtime_getter(), issue_number)

    def request_pr_reviewer_assignment(self, issue_number, username):
        return github_api.request_pr_reviewer_assignment(self._runtime_getter(), issue_number, username)

    def assign_issue_assignee(self, issue_number, username):
        return github_api.assign_issue_assignee(self._runtime_getter(), issue_number, username)

    def add_reaction(self, comment_id, reaction):
        return github_api.add_reaction(self._runtime_getter(), comment_id, reaction)

    def remove_issue_assignee(self, issue_number, username):
        return github_api.remove_issue_assignee(self._runtime_getter(), issue_number, username)

    def remove_pr_reviewer(self, issue_number, username):
        return github_api.remove_pr_reviewer(self._runtime_getter(), issue_number, username)

    def get_user_permission_status(self, username, required_permission="triage"):
        return github_api.get_user_permission_status(self._runtime_getter(), username, required_permission)

    def check_user_permission(self, username, required_permission="triage"):
        return github_api.check_user_permission(self._runtime_getter(), username, required_permission)

    def get_issue_or_pr_snapshot(self, issue_number):
        return github_api.github_api(self._runtime_getter(), "GET", f"issues/{issue_number}")

    def get_pull_request_reviews(self, issue_number):
        return reviews.get_pull_request_reviews(self._runtime_getter(), issue_number)


class _BootstrapLockServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def acquire(self):
        return lease_lock.acquire_state_issue_lease_lock(self._runtime_getter())

    def release(self) -> bool:
        return lease_lock.release_state_issue_lease_lock(self._runtime_getter())

    def refresh(self) -> bool:
        return lease_lock.ensure_state_issue_lease_lock_fresh(self._runtime_getter())


class _BootstrapHandlerServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def handle_issue_or_pr_opened(self, current_state):
        return lifecycle.handle_issue_or_pr_opened(self._runtime_getter(), current_state)

    def handle_labeled_event(self, current_state):
        return lifecycle.handle_labeled_event(self._runtime_getter(), current_state)

    def handle_issue_edited_event(self, current_state):
        return lifecycle.handle_issue_edited_event(self._runtime_getter(), current_state)

    def handle_closed_event(self, current_state):
        return lifecycle.handle_closed_event(self._runtime_getter(), current_state)

    def handle_pull_request_target_synchronize(self, current_state):
        return lifecycle.handle_pull_request_target_synchronize(self._runtime_getter(), current_state)

    def handle_comment_event(self, current_state):
        return comment_routing.handle_comment_event(self._runtime_getter(), current_state)

    def handle_manual_dispatch(self, current_state):
        return maintenance.handle_manual_dispatch(self._runtime_getter(), current_state)

    def handle_scheduled_check_result(self, current_state):
        return maintenance.handle_scheduled_check_result(self._runtime_getter(), current_state)


class _BootstrapReviewStateAdapterServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def _runtime(self):
        return self._runtime_getter()

    def maybe_record_head_observation_repair(self, issue_number, review_data):
        return lifecycle.maybe_record_head_observation_repair(self._runtime(), issue_number, review_data)

    def handle_transition_notice(self, current_state, issue_number, reviewer):
        return lifecycle.handle_transition_notice(self._runtime(), current_state, issue_number, reviewer)

    # Adapter-only mutable review-state compatibility surface.
    def ensure_review_entry(self, current_state, issue_number, create=False):
        return review_state.ensure_review_entry(current_state, issue_number, create=create)

    def set_current_reviewer(self, current_state, issue_number, reviewer, assignment_method="round-robin"):
        return review_state.set_current_reviewer(current_state, issue_number, reviewer, assignment_method=assignment_method)

    def update_reviewer_activity(self, current_state, issue_number, reviewer):
        return review_state.update_reviewer_activity(current_state, issue_number, reviewer)

    def mark_review_complete(self, current_state, issue_number, reviewer, source):
        return review_state.mark_review_complete(current_state, issue_number, reviewer, source)

    def is_triage_or_higher(self, username):
        return reviews.is_triage_or_higher(self._runtime(), username)

    def trigger_mandatory_approver_escalation(self, current_state, issue_number):
        return reviews.trigger_mandatory_approver_escalation(self._runtime(), current_state, issue_number)

    def satisfy_mandatory_approver_requirement(self, current_state, issue_number, approver):
        return reviews.satisfy_mandatory_approver_requirement(self._runtime(), current_state, issue_number, approver)

    def compute_reviewer_response_state(self, issue_number, review_data, *, issue_snapshot=None):
        return reviews.compute_reviewer_response_state(self._runtime(), issue_number, review_data, issue_snapshot=issue_snapshot)

    def rebuild_pr_approval_state(self, issue_number, review_data, *, pull_request=None, reviews=None):
        return reviews.rebuild_pr_approval_state(
            self._runtime(),
            issue_number,
            review_data,
            pull_request=pull_request,
            reviews=reviews,
        )


class _BootstrapCommandAdapterServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def _runtime(self):
        return self._runtime_getter()

    def handle_pass_command(self, current_state, issue_number, comment_author, reason, request=None):
        return commands.handle_pass_command(self._runtime(), current_state, issue_number, comment_author, reason, request=request)

    def handle_pass_until_command(self, current_state, issue_number, comment_author, return_date, reason, request=None):
        return commands.handle_pass_until_command(self._runtime(), current_state, issue_number, comment_author, return_date, reason, request=request)

    def handle_label_command(self, current_state, issue_number, label_string, request=None):
        return commands.handle_label_command(self._runtime(), current_state, issue_number, label_string, request=request)

    def handle_sync_members_command(self, current_state):
        return commands.handle_sync_members_command(self._runtime(), current_state)

    def handle_queue_command(self, current_state):
        return commands.handle_queue_command(self._runtime(), current_state)

    def handle_commands_command(self):
        return commands.handle_commands_command(self._runtime())

    def handle_claim_command(self, current_state, issue_number, comment_author, request=None):
        return commands.handle_claim_command(self._runtime(), current_state, issue_number, comment_author, request=request)

    def handle_release_command(self, current_state, issue_number, comment_author, args=None, request=None):
        return commands.handle_release_command(self._runtime(), current_state, issue_number, comment_author, args, request=request)

    def handle_rectify_command(self, current_state, issue_number, comment_author):
        return reconcile.handle_rectify_command(self._runtime(), current_state, issue_number, comment_author)

    def handle_assign_command(self, current_state, issue_number, username, request=None):
        return commands.handle_assign_command(self._runtime(), current_state, issue_number, username, request=request)

    def handle_assign_from_queue_command(self, current_state, issue_number, request=None):
        return commands.handle_assign_from_queue_command(self._runtime(), current_state, issue_number, request=request)

    def handle_accept_no_fls_changes_command(self, issue_number, comment_author, request=None):
        return automation.handle_accept_no_fls_changes_command(self._runtime(), issue_number, comment_author, request=request)

    def get_commands_help(self):
        return config.get_commands_help()

    def strip_code_blocks(self, comment_body):
        return commands.strip_code_blocks(comment_body)

    def parse_command(self, comment_body):
        return commands.parse_command(self._runtime(), comment_body)


class _BootstrapQueueAdapterServices:
    def get_next_reviewer(self, state, skip_usernames=None):
        return get_next_reviewer(state, skip_usernames)

    def record_assignment(self, state, github, issue_number, kind):
        return record_assignment(state, github, issue_number, kind)

    def reposition_member_as_next(self, state, username):
        return reposition_member_as_next(state, username)


class _BootstrapWorkflowAdapterServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def _runtime(self):
        return self._runtime_getter()

    def process_pass_until_expirations(self, state):
        return process_pass_until_expirations(state)

    def sync_members_with_queue(self, current_state):
        return sync_members_with_queue(self._runtime(), current_state)

    def sync_status_labels_for_items(self, current_state, issue_numbers):
        return reviews.sync_status_labels_for_items(self._runtime(), current_state, issue_numbers)

    def fetch_members(self):
        return members.fetch_members(self._runtime())


class _BootstrapAutomationAdapterServices:
    def __init__(self, runtime_getter):
        self._runtime_getter = runtime_getter

    def _runtime(self):
        return self._runtime_getter()

    def run_command(self, command, cwd=None, check=True):
        return automation.run_command(command, cwd, check)

    def summarize_output(self, result, limit=20):
        return automation.summarize_output(result, limit)

    def list_changed_files(self, repo_root):
        return automation.list_changed_files(repo_root)

    def get_default_branch(self):
        return automation.get_default_branch(self._runtime())

    def find_open_pr_for_branch_status(self, branch):
        return automation.find_open_pr_for_branch_status(self._runtime(), branch)

    def create_pull_request(self, branch, base, issue_number):
        return automation.create_pull_request(self._runtime(), branch, base, issue_number)

class _BootstrapStateLockAdapterServices:
    def __init__(self, runtime_getter, lock_services):
        self._runtime_getter = runtime_getter
        self._lock_services = lock_services

    def _runtime(self):
        return self._runtime_getter()

    def normalize_lock_metadata(self, lock_meta):
        return state_store.normalize_lock_metadata(lock_meta)

    def parse_iso8601_timestamp(self, value):
        return state_store.parse_iso8601_timestamp(value)

    def get_state_issue(self):
        return state_store.get_state_issue(self._runtime())

    def clear_lock_metadata(self):
        return lease_lock.clear_lock_metadata(self._runtime())

    def get_state_issue_snapshot(self):
        return state_store.get_state_issue_snapshot(self._runtime())

    def conditional_patch_state_issue(self, body, etag=None):
        return state_store.conditional_patch_state_issue(self._runtime(), body, etag)

    def render_state_issue_body(self, current_state, base_body=None, *, preserve_state_block=False):
        return state_store.render_state_issue_body(current_state, base_body, preserve_state_block=preserve_state_block)

    def get_state_issue_html_url(self):
        return lease_lock.get_state_issue_html_url(self._runtime())

    def get_lock_ref_display(self):
        return lease_lock.get_lock_ref_display(self._runtime())

    def get_lock_ref_snapshot(self):
        return lease_lock.get_lock_ref_snapshot(self._runtime())

    def build_lock_metadata(self, *args, **kwargs):
        return lease_lock.build_lock_metadata(self._runtime(), *args, **kwargs)

    def create_lock_commit(self, parent_sha, tree_sha, lock_meta):
        return lease_lock.create_lock_commit(self._runtime(), parent_sha, tree_sha, lock_meta)

    def cas_update_lock_ref(self, new_sha):
        return lease_lock.cas_update_lock_ref(self._runtime(), new_sha)

    def lock_is_currently_valid(self, lock_meta, now=None):
        return lease_lock.lock_is_currently_valid(self._runtime(), lock_meta, now)

    def renew_state_issue_lease_lock(self, context):
        return lease_lock.renew_state_issue_lease_lock(self._runtime(), context)

    def ensure_state_issue_lease_lock_fresh(self):
        return self._lock_services.refresh()

    def acquire_state_issue_lease_lock(self):
        return self._lock_services.acquire()

    def release_state_issue_lease_lock(self):
        return self._lock_services.release()

    def get_active_lease_context(self):
        return self._runtime().ACTIVE_LEASE_CONTEXT


class _BootstrapAdapterGroups:
    def __init__(self, *, github, review_state, commands, queue, workflow, automation, state_lock):
        self.github = github
        self.review_state = review_state
        self.commands = commands
        self.queue = queue
        self.workflow = workflow
        self.automation = automation
        self.state_lock = state_lock


def build_runtime(*, requests, sys, random, time, active_lease_context=None) -> ReviewerBotRuntime:
    runtime: ReviewerBotRuntime | None = None

    def runtime_getter() -> ReviewerBotRuntime:
        assert runtime is not None
        return runtime

    config_service = _EnvConfig()
    output_sink = _FileOutputSink(config_service)
    deferred_payload_loader = _JsonDeferredPayloadLoader(config_service)

    state_store_services = _BootstrapStateStoreServices(runtime_getter)
    github_services = _BootstrapGitHubServices(runtime_getter)
    lock_services = _BootstrapLockServices(runtime_getter)
    handlers = _BootstrapHandlerServices(runtime_getter)
    adapters = _BootstrapAdapterGroups(
        github=github_services,
        review_state=_BootstrapReviewStateAdapterServices(runtime_getter),
        commands=_BootstrapCommandAdapterServices(runtime_getter),
        queue=_BootstrapQueueAdapterServices(),
        workflow=_BootstrapWorkflowAdapterServices(runtime_getter),
        automation=_BootstrapAutomationAdapterServices(runtime_getter),
        state_lock=_BootstrapStateLockAdapterServices(runtime_getter, lock_services),
    )

    runtime = ReviewerBotRuntime(
        requests=requests,
        sys=sys,
        random=random,
        time=time,
        config=config_service,
        outputs=output_sink,
        deferred_payloads=deferred_payload_loader,
        state_store=state_store_services,
        github=github_services,
        locks=lock_services,
        handlers=handlers,
        adapters=adapters,
        active_lease_context=active_lease_context,
    )
    return runtime
