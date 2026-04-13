from __future__ import annotations

from dataclasses import dataclass

from scripts.reviewer_bot_lib import comment_application, lifecycle, reconcile

from .fake_runtime import FakeReviewerBotRuntime
from .reviewer_bot_builders import pull_request_payload, review_payload
from .reviewer_bot_env import set_env_values, set_workflow_run_event_payload
from .reviewer_bot_fakes import RouteGitHubApi, github_result


def review_submitted_payload(
    *,
    pr_number: int,
    review_id: int,
    source_event_key: str,
    source_submitted_at: str,
    source_review_state: str,
    source_commit_id: str,
    actor_login: str,
    source_run_id: int,
    source_run_attempt: int,
) -> dict:
    return {
        "payload_kind": "deferred_review_submitted",
        "schema_version": 3,
        "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_event_name": "pull_request_review",
        "source_event_action": "submitted",
        "source_event_key": source_event_key,
        "pr_number": pr_number,
        "review_id": review_id,
        "source_submitted_at": source_submitted_at,
        "source_review_state": source_review_state,
        "source_commit_id": source_commit_id,
        "actor_login": actor_login,
    }


def issue_comment_payload(
    *,
    pr_number: int,
    comment_id: int,
    source_event_key: str,
    body: str,
    comment_class: str,
    has_non_command_text: bool,
    source_created_at: str,
    actor_login: str,
    source_run_id: int,
    source_run_attempt: int,
) -> dict:
    del comment_class, has_non_command_text
    return {
        "payload_kind": "deferred_comment",
        "schema_version": 3,
        "source_workflow_name": "Reviewer Bot PR Comment Router",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-router.yml",
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_event_key": source_event_key,
        "pr_number": pr_number,
        "comment_id": comment_id,
        "comment_body": body,
        "comment_created_at": source_created_at,
        "comment_author": actor_login,
        "comment_author_id": 7001,
        "comment_user_type": "User",
        "comment_sender_type": "User",
        "comment_installation_id": None,
        "comment_performed_via_github_app": False,
        "issue_author": "dana",
        "issue_state": "open",
        "issue_labels": ["coding guideline"],
    }


def review_comment_payload(
    *,
    pr_number: int,
    comment_id: int,
    source_event_key: str,
    body: str,
    comment_class: str,
    has_non_command_text: bool,
    source_created_at: str,
    actor_login: str,
    actor_id: int,
    actor_class: str,
    pull_request_review_id: int,
    in_reply_to_id: int,
    source_run_id: int,
    source_run_attempt: int,
) -> dict:
    del comment_class, has_non_command_text, actor_class, pull_request_review_id, in_reply_to_id
    return {
        "payload_kind": "deferred_review_comment",
        "schema_version": 3,
        "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "source_event_name": "pull_request_review_comment",
        "source_event_action": "created",
        "source_event_key": source_event_key,
        "pr_number": pr_number,
        "comment_id": comment_id,
        "comment_body": body,
        "comment_created_at": source_created_at,
        "comment_author": actor_login,
        "comment_author_id": actor_id,
        "comment_user_type": "User",
        "comment_sender_type": "User",
        "comment_installation_id": None,
        "comment_performed_via_github_app": False,
        "issue_author": "dana",
        "issue_state": "open",
        "issue_labels": ["coding guideline"],
    }


@dataclass
class ReconcileHarness:
    monkeypatch: object
    payload: dict

    def __post_init__(self) -> None:
        self.github = RouteGitHubApi()
        self.runtime = FakeReviewerBotRuntime(self.monkeypatch, github=self.github)
        self.runtime.ACTIVE_LEASE_CONTEXT = object()
        self.config = self.runtime.config
        self.deferred_payloads = self.runtime.deferred_payloads
        self.runtime.stub_deferred_payload(self.payload)
        self.wrapper_set_trigger_from_payload(self.payload)

    def handle_workflow_run_event_result(self, state: dict) -> reconcile.WorkflowRunHandlerResult:
        return reconcile.handle_workflow_run_event_result(self.runtime, state)

    def set_payload(self, payload: dict) -> dict:
        self.payload = payload
        self.deferred_payloads.set_payload(payload)
        self.wrapper_set_trigger_from_payload(payload)
        return payload

    def wrapper_set_trigger_from_payload(self, payload: dict, *, conclusion: str = "success") -> None:
        set_workflow_run_event_payload(self.config, payload["source_workflow_name"])
        set_env_values(
            self.config,
            WORKFLOW_RUN_TRIGGERING_ID=payload["source_run_id"],
            WORKFLOW_RUN_TRIGGERING_ATTEMPT=payload["source_run_attempt"],
            WORKFLOW_RUN_TRIGGERING_CONCLUSION=conclusion,
        )

    set_trigger_from_payload = wrapper_set_trigger_from_payload

    def add_pull_request(
        self,
        *,
        pr_number: int,
        head_sha: str | None = None,
        author: str = "dana",
        labels: list[str] | None = None,
        requested_reviewers: list[str] | None = None,
        status_code: int = 200,
    ) -> None:
        payload = pull_request_payload(
            pr_number,
            head_sha=head_sha or "",
            author=author,
        )
        if head_sha is None:
            payload.pop("head", None)
        payload["labels"] = [{"name": label} for label in (labels or [])]
        if requested_reviewers is not None:
            payload["requested_reviewers"] = [
                {"login": reviewer} for reviewer in requested_reviewers
            ]
        self.github.add_request("GET", f"pulls/{pr_number}", status_code=status_code, payload=payload)

    def add_review(
        self,
        *,
        pr_number: int,
        review_id: int,
        submitted_at: str,
        state: str,
        commit_id: str,
        author: str,
        status_code: int = 200,
    ) -> None:
        self.github.add_request(
            "GET",
            f"pulls/{pr_number}/reviews/{review_id}",
            status_code=status_code,
            payload=review_payload(
                review_id,
                state=state,
                submitted_at=submitted_at,
                commit_id=commit_id,
                author=author,
            ),
        )

    def add_reviews_page(self, *, pr_number: int, reviews: list[dict], page: int = 1) -> None:
        self.github.add_request(
            "GET",
            f"pulls/{pr_number}/reviews?per_page=100&page={page}",
            status_code=200,
            payload=reviews,
        )

    def add_issue_comment(
        self,
        *,
        comment_id: int,
        body: str,
        author: str,
        author_type: str,
        author_association: str,
        performed_via_github_app=None,
        status_code: int = 200,
    ) -> None:
        self.github.add_request(
            "GET",
            f"issues/comments/{comment_id}",
            status_code=status_code,
            payload={
                "body": body,
                "user": {"login": author, "type": author_type},
                "author_association": author_association,
                "performed_via_github_app": performed_via_github_app,
            },
        )

    def add_review_comment(
        self,
        *,
        comment_id: int,
        body: str,
        author: str,
        author_type: str,
        author_association: str,
        performed_via_github_app=None,
        status_code: int = 200,
    ) -> None:
        self.github.add_request(
            "GET",
            f"pulls/comments/{comment_id}",
            status_code=status_code,
            payload={
                "body": body,
                "user": {"login": author, "type": author_type},
                "author_association": author_association,
                "performed_via_github_app": performed_via_github_app,
            },
        )

    def add_request_failure(
        self,
        *,
        endpoint: str,
        status_code: int,
        payload: dict,
        retry_attempts: int = 1,
        failure_kind: str | None = None,
    ) -> None:
        self.github.add_request(
            "GET",
            endpoint,
            result=github_result(
                status_code,
                payload,
                retry_attempts=retry_attempts,
                failure_kind=failure_kind,
            ),
        )

    def stub_head_repair(self, *, changed: bool = False, outcome: str = "unchanged") -> None:
        self.runtime.adapters.review_state.maybe_record_head_observation_repair = lambda issue_number, review_data: lifecycle.HeadObservationRepairResult(
            changed=changed,
            outcome=outcome,
        )

    def stub_review_rebuild(self, *, changed: bool = False) -> None:
        self.monkeypatch.setattr(
            reconcile,
            "_record_review_rebuild",
            lambda bot, state_obj, issue_number, review_data: changed,
        )

    def stub_comment_classification(self, classified: dict | None = None, *, func=None) -> None:
        if func is None:
            def default_func(bot, body):
                return classified

            func = default_func
        self.monkeypatch.setattr(reconcile, "classify_comment_payload", func)

    def stub_apply_comment_command(self, result: bool | None = None, *, func=None) -> None:
        if func is None:
            def default_func(*args, **kwargs):
                return result

            func = default_func
        self.monkeypatch.setattr(comment_application, "apply_comment_command", func)

    def run(self, state: dict) -> bool:
        return self.handle_workflow_run_event_result(state).state_changed
