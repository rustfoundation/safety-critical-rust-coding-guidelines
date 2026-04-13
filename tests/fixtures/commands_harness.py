from __future__ import annotations

import subprocess

from scripts.reviewer_bot_core.comment_routing_policy import PrCommentRouterOutcome
from scripts.reviewer_bot_lib import automation as automation_module
from scripts.reviewer_bot_lib import commands as commands_module
from scripts.reviewer_bot_lib import comment_routing as comment_routing_module
from scripts.reviewer_bot_lib import event_inputs
from scripts.reviewer_bot_lib import maintenance as maintenance_module
from scripts.reviewer_bot_lib import reconcile as reconcile_module
from scripts.reviewer_bot_lib.config import AssignmentAttempt
from scripts.reviewer_bot_lib.context import (
    CommentEventRequest,
    PrCommentAdmission,
)

from .fake_runtime import FakeReviewerBotRuntime
from .reviewer_bot_builders import (
    build_assignment_request,
    build_comment_event_request,
    build_pr_comment_admission,
    build_privileged_command_request,
)
from .reviewer_bot_env import set_env_values
from .reviewer_bot_recorders import record_comment_side_effects, record_comments


class AutomationRunner:
    def __init__(self):
        self._results: dict[tuple[str, ...], subprocess.CompletedProcess] = {}
        self.calls: list[tuple[list[str], object, bool]] = []

    def when(self, command: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self._results[tuple(command)] = subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)

    def run(self, command, cwd, check=False):
        command_list = list(command)
        self.calls.append((command_list, cwd, check))
        key = tuple(command_list)
        if key not in self._results:
            raise AssertionError(f"Unexpected command: {command_list}")
        return self._results[key]


class CommandHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.runtime = FakeReviewerBotRuntime(monkeypatch)
        self.runtime.ACTIVE_LEASE_CONTEXT = object()
        self.config = self.runtime.config
        self.github = self.runtime.github
        self.handlers = self.runtime.handlers

    def wrapper_set_comment_command(
        self,
        *,
        issue_number: int,
        actor: str,
        body: str,
        issue_author: str,
        is_pull_request: bool = False,
        author_association: str = "",
        workflow_file: str = "",
        repository: str = "",
        ref: str = "",
        comment_id: int = 100,
        created_at: str = "2026-03-17T10:00:00Z",
        ) -> None:
        values = {
            "ISSUE_NUMBER": issue_number,
            "IS_PULL_REQUEST": str(is_pull_request).lower(),
            "ISSUE_AUTHOR": issue_author,
            "COMMENT_USER_TYPE": "User",
            "COMMENT_AUTHOR": actor,
            "COMMENT_ID": comment_id,
            "COMMENT_CREATED_AT": created_at,
            "COMMENT_BODY": body,
        }
        if author_association:
            values["COMMENT_AUTHOR_ASSOCIATION"] = author_association
        if workflow_file:
            values["CURRENT_WORKFLOW_FILE"] = workflow_file
        if repository:
            values["GITHUB_REPOSITORY"] = repository
        if ref:
            values["GITHUB_REF"] = ref
        set_env_values(self.config, **values)

    def wrapper_set_assignment_context(self, *, issue_author: str, is_pull_request: bool) -> None:
        set_env_values(self.config, ISSUE_AUTHOR=issue_author, IS_PULL_REQUEST=str(is_pull_request).lower())

    def wrapper_set_privileged_context(
        self,
        *,
        labels: list[str],
        is_pull_request: bool = False,
        target_repo_root=None,
    ) -> None:
        import json

        set_env_values(self.config, IS_PULL_REQUEST=str(is_pull_request).lower(), ISSUE_LABELS=json.dumps(labels))
        if target_repo_root is not None:
            self.config.set("REVIEWER_BOT_TARGET_REPO_ROOT", target_repo_root)

    def wrapper_set_manual_dispatch(self, *, source_event_key: str) -> None:
        set_env_values(self.config, MANUAL_ACTION="execute-pending-privileged-command", PRIVILEGED_SOURCE_EVENT_KEY=source_event_key)

    set_comment_command = wrapper_set_comment_command
    set_assignment_context = wrapper_set_assignment_context
    set_privileged_context = wrapper_set_privileged_context
    set_manual_dispatch = wrapper_set_manual_dispatch

    def capture_posted_comments(self):
        return record_comments(self.runtime)

    def capture_comment_side_effects(self):
        return record_comment_side_effects(self.runtime)

    def stub_assignees(self, assignees):
        self.runtime.github.get_issue_assignees = lambda issue_number: assignees

    def stub_assignment(self, *, success: bool = True, status_code: int = 201):
        def attempt(issue_number, username):
            return AssignmentAttempt(success=success, status_code=status_code)

        self.runtime.github.request_pr_reviewer_assignment = attempt
        self.runtime.github.assign_issue_assignee = attempt

    def stub_permission(self, status: str) -> None:
        self.runtime.github.get_user_permission_status = lambda username, required_permission="triage": status

    def stub_handler(self, name: str, func) -> None:
        self.handlers.stub(name, func)

    def automation_runner(self) -> AutomationRunner:
        runner = AutomationRunner()
        self._monkeypatch.setattr(automation_module, "run_command", runner.run)
        self.runtime.adapters.automation.run_command = runner.run
        return runner

    def assignment_request(self, *, issue_number: int):
        return event_inputs.build_assignment_request(self.runtime, issue_number=issue_number)

    def typed_assignment_request(
        self,
        *,
        issue_number: int,
        issue_author: str = "",
        is_pull_request: bool = False,
        issue_labels: tuple[str, ...] = (),
        repo_owner: str = "",
        repo_name: str = "",
    ):
        return build_assignment_request(
            issue_number=issue_number,
            issue_author=issue_author,
            is_pull_request=is_pull_request,
            issue_labels=issue_labels,
            repo_owner=repo_owner,
            repo_name=repo_name,
        )

    def privileged_request(self, *, issue_number: int, actor: str = "", command_name: str = ""):
        return event_inputs.build_privileged_command_request(
            self.runtime,
            issue_number=issue_number,
            actor=actor,
            command_name=command_name,
        )

    def typed_privileged_request(
        self,
        *,
        issue_number: int,
        actor: str = "",
        command_name: str = "",
        is_pull_request: bool = False,
        issue_labels: tuple[str, ...] = (),
    ):
        return build_privileged_command_request(
            issue_number=issue_number,
            actor=actor,
            command_name=command_name,
            is_pull_request=is_pull_request,
            issue_labels=issue_labels,
        )

    def typed_comment_request(
        self,
        *,
        issue_number: int,
        actor: str,
        body: str,
        issue_author: str,
        is_pull_request: bool = False,
        issue_state: str = "open",
        issue_labels: tuple[str, ...] = (),
        comment_id: int = 100,
        created_at: str = "2026-03-17T10:00:00Z",
    ) -> CommentEventRequest:
        return build_comment_event_request(
            issue_number=issue_number,
            is_pull_request=is_pull_request,
            issue_state=issue_state,
            issue_author=issue_author,
            issue_labels=issue_labels,
            comment_id=comment_id,
            comment_author=actor,
            comment_body=body,
            comment_created_at=created_at,
            comment_user_type="User",
        )

    def typed_pr_admission(
        self,
        *,
        repository: str = "",
        pr_head_full_name: str = "",
        pr_author: str = "",
        issue_state: str = "open",
        issue_labels: tuple[str, ...] = (),
        comment_author_id: int = 200,
        run_id: int = 0,
        run_attempt: int = 0,
        author_association: str = "",
        workflow_file: str = "",
        ref: str = "",
    ) -> PrCommentAdmission:
        del author_association, workflow_file, ref
        if repository and not pr_head_full_name:
            pr_head_full_name = repository
        if repository and not pr_author:
            pr_author = "trusted-author"
        return build_pr_comment_admission(
            route_outcome=PrCommentRouterOutcome.TRUSTED_DIRECT,
            declared_trust_class="pr_trusted_direct",
            github_repository=repository,
            pr_head_full_name=pr_head_full_name,
            pr_author=pr_author,
            issue_state=issue_state,
            issue_labels=issue_labels,
            comment_author_id=comment_author_id,
            github_run_id=run_id,
            github_run_attempt=run_attempt,
        )

    def typed_trust_context(self, **kwargs):
        return self.typed_pr_admission(**kwargs)

    def handle_assign(self, state: dict, issue_number: int, username: str, *, request=None):
        return commands_module.handle_assign_command(
            self.runtime,
            state,
            issue_number,
            username,
            request=request or self.assignment_request(issue_number=issue_number),
        )

    def handle_claim(self, state: dict, issue_number: int, comment_author: str, *, request=None):
        return commands_module.handle_claim_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
            request=request or self.assignment_request(issue_number=issue_number),
        )

    def handle_pass(self, state: dict, issue_number: int, comment_author: str, reason: str | None, *, request=None):
        return commands_module.handle_pass_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
            reason,
            request=request or self.assignment_request(issue_number=issue_number),
        )

    def handle_pass_until(self, state: dict, issue_number: int, comment_author: str, return_date: str, reason: str | None, *, request=None):
        return commands_module.handle_pass_until_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
            return_date,
            reason,
            request=request or self.assignment_request(issue_number=issue_number),
        )

    def handle_release(self, state: dict, issue_number: int, comment_author: str, args=None, *, request=None):
        return commands_module.handle_release_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
            args,
            request=request or self.assignment_request(issue_number=issue_number),
        )

    def handle_assign_from_queue(self, state: dict, issue_number: int, *, request=None):
        return commands_module.handle_assign_from_queue_command(
            self.runtime,
            state,
            issue_number,
            request=request or self.assignment_request(issue_number=issue_number),
        )

    def handle_rectify(self, state: dict, issue_number: int, comment_author: str):
        return reconcile_module.handle_rectify_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
        )

    def handle_accept_no_fls_changes(self, issue_number: int, comment_author: str, *, request=None):
        result = automation_module.handle_accept_no_fls_changes_command(
            self.runtime,
            issue_number,
            comment_author,
            request=request or self.privileged_request(issue_number=issue_number, actor=comment_author, command_name="accept-no-fls-changes"),
        )
        return result.result_message or "", result.status == "executed"

    def handle_comment_event(
        self,
        state: dict,
        *,
        request: CommentEventRequest | None = None,
        pr_admission: PrCommentAdmission | None = None,
        trust_context: PrCommentAdmission | None = None,
    ):
        return comment_routing_module.handle_comment_event(
            self.runtime,
            state,
            request or event_inputs.build_comment_event_request(self.runtime),
            pr_admission or trust_context or event_inputs.build_pr_comment_admission(self.runtime),
        )

    def handle_manual_dispatch(self, state: dict):
        return maintenance_module.handle_manual_dispatch(self.runtime, state)
