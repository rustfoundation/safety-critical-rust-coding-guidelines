from __future__ import annotations

from scripts.reviewer_bot_core.comment_routing_policy import PrCommentRouterOutcome
from scripts.reviewer_bot_lib import comment_routing, event_inputs
from scripts.reviewer_bot_lib.context import (
    CommentEventRequest,
    PrCommentAdmission,
)

from .fake_runtime import FakeReviewerBotRuntime
from .reviewer_bot_builders import (
    build_comment_event_request,
    build_pr_comment_admission,
)
from .reviewer_bot_env import set_env_values
from .reviewer_bot_fakes import RouteGitHubApi
from .reviewer_bot_recorders import record_comment_side_effects


class CommentRoutingHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.github = RouteGitHubApi()
        self.runtime = FakeReviewerBotRuntime(monkeypatch, github=self.github)
        self.runtime.ACTIVE_LEASE_CONTEXT = object()
        self.config = self.runtime.config
        self.handlers = self.runtime.handlers

    def env_build_request(self, *, issue_number: int | None = None):
        return event_inputs.build_comment_event_request(self.runtime, issue_number=issue_number)

    def env_build_pr_admission(self):
        return event_inputs.build_pr_comment_admission(self.runtime)

    wrapper_request = env_build_request
    wrapper_pr_admission = env_build_pr_admission

    def handle_comment_event(self, state: dict, request: CommentEventRequest | None = None, pr_admission: PrCommentAdmission | None = None):
        return comment_routing.handle_comment_event(
            self.runtime,
            state,
            request or self.env_build_request(),
            pr_admission,
        )

    def request(
        self,
        *,
        issue_number: int,
        is_pull_request: bool,
        issue_state: str = "open",
        issue_author: str = "",
        issue_labels: tuple[str, ...] = (),
        comment_id: int = 100,
        comment_author: str,
        comment_author_id: int = 200,
        comment_body: str,
        comment_created_at: str = "2026-03-17T10:00:00Z",
        comment_source_event_key: str = "",
        comment_user_type: str = "User",
    ) -> CommentEventRequest:
        return build_comment_event_request(
            issue_number=issue_number,
            is_pull_request=is_pull_request,
            issue_state=issue_state,
            issue_author=issue_author,
            issue_labels=issue_labels,
            comment_id=comment_id,
            comment_author=comment_author,
            comment_author_id=comment_author_id,
            comment_body=comment_body,
            comment_created_at=comment_created_at,
            comment_source_event_key=comment_source_event_key,
            comment_user_type=comment_user_type,
            comment_sender_type="User",
            comment_installation_id=None,
            comment_performed_via_github_app=False,
        )

    def pr_admission(
        self,
        *,
        route_outcome: PrCommentRouterOutcome = PrCommentRouterOutcome.TRUSTED_DIRECT,
        declared_trust_class: str = "pr_trusted_direct",
        github_repository: str = "",
        pr_head_full_name: str = "",
        pr_author: str = "",
        issue_state: str = "open",
        issue_labels: tuple[str, ...] = (),
        comment_author_id: int = 200,
        github_run_id: int = 0,
        github_run_attempt: int = 0,
        comment_author_association: str = "",
        current_workflow_file: str = "",
        github_ref: str = "",
    ) -> PrCommentAdmission:
        del comment_author_association, current_workflow_file, github_ref
        if github_repository and not pr_head_full_name:
            pr_head_full_name = github_repository
        if github_repository and not pr_author:
            pr_author = "trusted-author"
        return build_pr_comment_admission(
            route_outcome=route_outcome,
            declared_trust_class=declared_trust_class,
            github_repository=github_repository,
            pr_head_full_name=pr_head_full_name,
            pr_author=pr_author,
            issue_state=issue_state,
            issue_labels=issue_labels,
            comment_author_id=comment_author_id,
            github_run_id=github_run_id,
            github_run_attempt=github_run_attempt,
        )

    def trust_context(self, **kwargs):
        return self.pr_admission(**kwargs)

    def add_pull_request_metadata(self, *, issue_number: int, head_repo_full_name: str, pr_author: str) -> None:
        payload = {"head": {"repo": {"full_name": head_repo_full_name}}, "user": {"login": pr_author}}
        self.github.add_api("GET", f"pulls/{issue_number}", payload)
        self.github.add_request("GET", f"pulls/{issue_number}", status_code=200, payload=payload)

    def capture_comment_side_effects(self):
        return record_comment_side_effects(self.runtime)

    def wrapper_apply_inputs(
        self,
        *,
        issue_number: int,
        is_pull_request: bool,
        issue_state: str = "open",
        issue_author: str = "",
        issue_labels: str = "[]",
        comment_id: int = 100,
        comment_author: str,
        comment_author_id: int = 200,
        comment_body: str,
        comment_created_at: str = "2026-03-17T10:00:00Z",
        comment_user_type: str = "User",
        comment_author_association: str = "",
        current_workflow_file: str = "",
        github_repository: str = "",
        github_ref: str = "",
        pr_head_full_name: str = "",
        pr_author: str = "",
    ) -> None:
        del comment_author_association, current_workflow_file, github_ref
        values = {
            "EVENT_NAME": "issue_comment",
            "ISSUE_NUMBER": issue_number,
            "IS_PULL_REQUEST": str(is_pull_request).lower(),
            "ISSUE_STATE": issue_state,
            "ISSUE_LABELS": issue_labels,
            "ISSUE_AUTHOR": issue_author,
            "COMMENT_ID": comment_id,
            "COMMENT_AUTHOR": comment_author,
            "COMMENT_AUTHOR_ID": comment_author_id,
            "COMMENT_BODY": comment_body,
            "COMMENT_CREATED_AT": comment_created_at,
            "COMMENT_USER_TYPE": comment_user_type,
            "COMMENT_SENDER_TYPE": "User",
            "COMMENT_PERFORMED_VIA_GITHUB_APP": "false",
            "REVIEWER_BOT_ROUTE_OUTCOME": "trusted_direct",
            "REVIEWER_BOT_TRUST_CLASS": "pr_trusted_direct",
        }
        if github_repository:
            values["GITHUB_REPOSITORY"] = github_repository
        if pr_head_full_name:
            values["PR_HEAD_FULL_NAME"] = pr_head_full_name
        if pr_author:
            values["PR_AUTHOR"] = pr_author
        set_env_values(self.config, **values)

    apply_wrapper_inputs = wrapper_apply_inputs
