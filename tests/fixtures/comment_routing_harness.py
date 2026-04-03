from __future__ import annotations

from scripts.reviewer_bot_lib import comment_routing, event_inputs
from scripts.reviewer_bot_lib.context import CommentEventRequest, PrCommentTrustContext

from .fake_runtime import FakeReviewerBotRuntime
from .reviewer_bot_builders import (
    build_comment_event_request,
    build_pr_comment_trust_context,
)
from .reviewer_bot_env import set_env_values
from .reviewer_bot_fakes import RouteGitHubApi
from .reviewer_bot_recorders import record_comment_side_effects


class CommentRoutingHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.github = RouteGitHubApi()
        self.runtime = FakeReviewerBotRuntime(monkeypatch, github=self.github)
        self.config = self.runtime.config

    def env_build_request(self, *, issue_number: int | None = None):
        return event_inputs.build_comment_event_request(issue_number=issue_number)

    def env_build_trust_context(self):
        return event_inputs.build_pr_comment_trust_context()

    wrapper_request = env_build_request
    wrapper_trust_context = env_build_trust_context

    def handle_comment_event(self, state: dict, request: CommentEventRequest | None = None, trust_context: PrCommentTrustContext | None = None):
        return comment_routing.handle_comment_event(
            self.runtime,
            state,
            request or self.env_build_request(),
            trust_context,
        )

    def build_observer_payload(self, issue_number: int, request: CommentEventRequest | None = None, trust_context: PrCommentTrustContext | None = None):
        return comment_routing.build_pr_comment_observer_payload(
            self.runtime,
            issue_number,
            request or self.env_build_request(issue_number=issue_number),
            trust_context or self.env_build_trust_context(),
        )

    def request(
        self,
        *,
        issue_number: int,
        is_pull_request: bool,
        issue_state: str = "open",
        issue_author: str = "",
        comment_id: int = 100,
        comment_author: str,
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
            comment_id=comment_id,
            comment_author=comment_author,
            comment_body=comment_body,
            comment_created_at=comment_created_at,
            comment_source_event_key=comment_source_event_key,
            comment_user_type=comment_user_type,
            comment_sender_type="",
            comment_installation_id="",
            comment_performed_via_github_app=False,
        )

    def trust_context(
        self,
        *,
        github_repository: str = "",
        comment_author_association: str = "",
        current_workflow_file: str = "",
        github_ref: str = "",
        github_run_id: int = 0,
        github_run_attempt: int = 0,
    ) -> PrCommentTrustContext:
        return build_pr_comment_trust_context(
            github_repository=github_repository,
            comment_author_association=comment_author_association,
            current_workflow_file=current_workflow_file,
            github_ref=github_ref,
            github_run_id=github_run_id,
            github_run_attempt=github_run_attempt,
        )

    def add_pull_request_metadata(
        self,
        *,
        issue_number: int,
        head_repo_full_name: str,
        pr_author: str,
    ) -> None:
        payload = {
            "head": {"repo": {"full_name": head_repo_full_name}},
            "user": {"login": pr_author},
        }
        self.github.add_api(
            "GET",
            f"pulls/{issue_number}",
            payload,
        )
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
        comment_id: int = 100,
        comment_author: str,
        comment_body: str,
        comment_created_at: str = "2026-03-17T10:00:00Z",
        comment_user_type: str = "User",
        comment_author_association: str = "",
        current_workflow_file: str = "",
        github_repository: str = "",
        github_ref: str = "",
    ) -> None:
        values = {
            "ISSUE_NUMBER": issue_number,
            "IS_PULL_REQUEST": str(is_pull_request).lower(),
            "ISSUE_STATE": issue_state,
            "ISSUE_AUTHOR": issue_author,
            "COMMENT_ID": comment_id,
            "COMMENT_AUTHOR": comment_author,
            "COMMENT_BODY": comment_body,
            "COMMENT_CREATED_AT": comment_created_at,
            "COMMENT_USER_TYPE": comment_user_type,
        }
        if comment_author_association:
            values["COMMENT_AUTHOR_ASSOCIATION"] = comment_author_association
        if current_workflow_file:
            values["CURRENT_WORKFLOW_FILE"] = current_workflow_file
        if github_repository:
            values["GITHUB_REPOSITORY"] = github_repository
        if github_ref:
            values["GITHUB_REF"] = github_ref
        set_env_values(self.config, **values)

    apply_wrapper_inputs = wrapper_apply_inputs
