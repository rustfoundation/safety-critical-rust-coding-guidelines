from __future__ import annotations

from dataclasses import dataclass

from scripts import reviewer_bot
from scripts.reviewer_bot_lib.context import CommentEventRequest, PrCommentTrustContext
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime

from .reviewer_bot_fakes import RouteGitHubApi


class _ConfigBag:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.values: dict[str, str] = {}

    def get(self, name: str, default: str = "") -> str:
        return self.values.get(name, default)

    def set(self, name: str, value) -> None:
        rendered = str(value)
        self.values[name] = rendered
        self._monkeypatch.setenv(name, rendered)


@dataclass
class SideEffects:
    comments: list[tuple[int, str]]
    reactions: list[tuple[int, str]]


class CommentRoutingHarness:
    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self.config = _ConfigBag(monkeypatch)
        self.github = RouteGitHubApi()
        self.runtime = ReviewerBotRuntime(reviewer_bot, config=self.config, github=self.github)
        self._monkeypatch.setattr(reviewer_bot, "RUNTIME", self.runtime)

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
        return CommentEventRequest(
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
        return PrCommentTrustContext(
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

    def side_effects(self) -> SideEffects:
        comments: list[tuple[int, str]] = []
        reactions: list[tuple[int, str]] = []
        self._monkeypatch.setattr(
            reviewer_bot,
            "post_comment",
            lambda issue_number, body: comments.append((issue_number, body)) or True,
        )
        self._monkeypatch.setattr(
            reviewer_bot,
            "add_reaction",
            lambda comment_id, reaction: reactions.append((comment_id, reaction)) or True,
        )
        return SideEffects(comments=comments, reactions=reactions)

    def set_wrapper_env(
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
        self.config.set("ISSUE_NUMBER", issue_number)
        self.config.set("IS_PULL_REQUEST", str(is_pull_request).lower())
        self.config.set("ISSUE_STATE", issue_state)
        self.config.set("ISSUE_AUTHOR", issue_author)
        self.config.set("COMMENT_ID", comment_id)
        self.config.set("COMMENT_AUTHOR", comment_author)
        self.config.set("COMMENT_BODY", comment_body)
        self.config.set("COMMENT_CREATED_AT", comment_created_at)
        self.config.set("COMMENT_USER_TYPE", comment_user_type)
        if comment_author_association:
            self.config.set("COMMENT_AUTHOR_ASSOCIATION", comment_author_association)
        if current_workflow_file:
            self.config.set("CURRENT_WORKFLOW_FILE", current_workflow_file)
        if github_repository:
            self.config.set("GITHUB_REPOSITORY", github_repository)
        if github_ref:
            self.config.set("GITHUB_REF", github_ref)
