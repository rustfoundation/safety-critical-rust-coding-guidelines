from __future__ import annotations

import subprocess

from scripts import reviewer_bot
from scripts.reviewer_bot_lib import automation as automation_module
from scripts.reviewer_bot_lib import commands as commands_module
from scripts.reviewer_bot_lib import comment_routing as comment_routing_module
from scripts.reviewer_bot_lib import event_inputs

from .fake_runtime import FakeReviewerBotRuntime
from .reviewer_bot_env import set_env_values
from .reviewer_bot_recorders import record_comments


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
        self.config = self.runtime.config
        self._monkeypatch.setattr(reviewer_bot, "RUNTIME", self.runtime)

    def set_comment_command(
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

    def set_assignment_context(self, *, issue_author: str, is_pull_request: bool) -> None:
        set_env_values(self.config, ISSUE_AUTHOR=issue_author, IS_PULL_REQUEST=str(is_pull_request).lower())

    def set_privileged_context(
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

    def set_manual_dispatch(self, *, source_event_key: str) -> None:
        set_env_values(self.config, MANUAL_ACTION="execute-pending-privileged-command", PRIVILEGED_SOURCE_EVENT_KEY=source_event_key)

    def capture_posted_comments(self):
        return record_comments(self.runtime)

    def stub_assignees(self, assignees):
        self.runtime.get_issue_assignees = lambda issue_number: assignees

    def stub_assignment(self, *, success: bool = True, status_code: int = 201):
        self.runtime.request_reviewer_assignment = lambda issue_number, username: reviewer_bot.AssignmentAttempt(
            success=success, status_code=status_code
        )

    def stub_permission(self, status: str) -> None:
        self.runtime.get_user_permission_status = lambda username, required_permission="triage": status

    def stub_handler(self, name: str, func) -> None:
        self.runtime.stub_handler(name, func)

    def automation_runner(self) -> AutomationRunner:
        runner = AutomationRunner()
        self._monkeypatch.setattr(automation_module, "run_command", runner.run)
        self.runtime.run_command = runner.run
        return runner

    def assignment_request(self, *, issue_number: int):
        return event_inputs.build_assignment_request(issue_number=issue_number)

    def privileged_request(self, *, issue_number: int, actor: str = "", command_name: str = ""):
        return event_inputs.build_privileged_command_request(
            issue_number=issue_number,
            actor=actor,
            command_name=command_name,
        )

    def handle_assign(self, state: dict, issue_number: int, username: str):
        return commands_module.handle_assign_command(
            self.runtime,
            state,
            issue_number,
            username,
            request=self.assignment_request(issue_number=issue_number),
        )

    def handle_claim(self, state: dict, issue_number: int, comment_author: str):
        return commands_module.handle_claim_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
            request=self.assignment_request(issue_number=issue_number),
        )

    def handle_pass(self, state: dict, issue_number: int, comment_author: str, reason: str | None):
        return commands_module.handle_pass_command(
            self.runtime,
            state,
            issue_number,
            comment_author,
            reason,
            request=self.assignment_request(issue_number=issue_number),
        )

    def handle_accept_no_fls_changes(self, issue_number: int, comment_author: str):
        return automation_module.handle_accept_no_fls_changes_command(
            self.runtime,
            issue_number,
            comment_author,
            request=self.privileged_request(issue_number=issue_number, actor=comment_author, command_name="accept-no-fls-changes"),
        )

    def handle_comment_event(self, state: dict):
        return comment_routing_module.handle_comment_event(
            self.runtime,
            state,
            event_inputs.build_comment_event_request(),
            event_inputs.build_pr_comment_trust_context(),
        )
