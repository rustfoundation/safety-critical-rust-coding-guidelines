import io
import json
import os
import subprocess
import zipfile
from datetime import timedelta
from pathlib import Path
from typing import get_type_hints

import pytest
import yaml

from builder import build_cli
from scripts import reviewer_bot
from scripts.reviewer_bot_lib import comment_routing, sweeper
from scripts.reviewer_bot_lib.context import ReviewerBotContext


class FakeGitHubResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.headers = headers or {}
        self.content = b"" if payload is None and not text else b"x"

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def make_zip_payload(file_name: str, payload: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(file_name, json.dumps(payload))
    return buffer.getvalue()


def make_state(epoch: str = "freshness_v15"):
    return {
        "schema_version": reviewer_bot.STATE_SCHEMA_VERSION,
        "freshness_runtime_epoch": epoch,
        "last_updated": None,
        "current_index": 0,
        "queue": [],
        "pass_until": [],
        "recent_assignments": [],
        "active_reviews": {},
    }


def valid_reviewer_board_metadata():
    return {
        "data": {
            "organization": {
                "projectV2": {
                    "id": "PVT_kwDOB",
                    "title": "Reviewer Board",
                    "fields": {
                        "nodes": [
                            {
                                "__typename": "ProjectV2SingleSelectField",
                                "id": "field-review-state",
                                "name": "Review State",
                                "options": [
                                    {"id": "opt-ar", "name": "Awaiting Reviewer"},
                                    {"id": "opt-ac", "name": "Awaiting Contributor"},
                                    {"id": "opt-aw", "name": "Awaiting Write Approval"},
                                    {"id": "opt-done", "name": "Done"},
                                    {"id": "opt-unassigned", "name": "Unassigned"},
                                ],
                            },
                            {
                                "__typename": "ProjectV2Field",
                                "dataType": "TEXT",
                                "id": "field-reviewer",
                                "name": "Reviewer",
                            },
                            {
                                "__typename": "ProjectV2Field",
                                "dataType": "DATE",
                                "id": "field-assigned-at",
                                "name": "Assigned At",
                            },
                            {
                                "__typename": "ProjectV2Field",
                                "dataType": "DATE",
                                "id": "field-waiting-since",
                                "name": "Waiting Since",
                            },
                            {
                                "__typename": "ProjectV2SingleSelectField",
                                "id": "field-needs-attention",
                                "name": "Needs Attention",
                                "options": [
                                    {"id": "opt-no", "name": "No"},
                                    {"id": "opt-warning", "name": "Warning Sent"},
                                    {"id": "opt-notice", "name": "Transition Notice Sent"},
                                    {"id": "opt-triage", "name": "Triage Approval Required"},
                                    {"id": "opt-repair", "name": "Projection Repair Required"},
                                ],
                            },
                        ]
                    },
                }
            }
        }
    }


def iso_z(dt):
    return dt.isoformat().replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    keys = [
        "EVENT_NAME",
        "EVENT_ACTION",
        "ISSUE_NUMBER",
        "ISSUE_AUTHOR",
        "IS_PULL_REQUEST",
        "COMMENT_BODY",
        "COMMENT_AUTHOR",
        "COMMENT_ID",
        "COMMENT_SOURCE_EVENT_KEY",
        "COMMENT_CREATED_AT",
        "COMMENT_USER_TYPE",
        "COMMENT_AUTHOR_ASSOCIATION",
        "COMMENT_SENDER_TYPE",
        "COMMENT_INSTALLATION_ID",
        "COMMENT_PERFORMED_VIA_GITHUB_APP",
        "CURRENT_WORKFLOW_FILE",
        "GITHUB_REPOSITORY",
        "GITHUB_REF",
        "ISSUE_BODY",
        "ISSUE_UPDATED_AT",
        "ISSUE_CHANGES_TITLE_FROM",
        "ISSUE_CHANGES_BODY_FROM",
        "SENDER_LOGIN",
        "DEFERRED_CONTEXT_PATH",
        "DEFERRED_ARTIFACT_RETENTION_DAYS",
        "WORKFLOW_RUN_TRIGGERING_NAME",
        "WORKFLOW_RUN_TRIGGERING_ID",
        "WORKFLOW_RUN_TRIGGERING_ATTEMPT",
        "WORKFLOW_RUN_TRIGGERING_CONCLUSION",
        "MANUAL_ACTION",
        "PRIVILEGED_SOURCE_EVENT_KEY",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", object())
    monkeypatch.setattr(reviewer_bot, "_reviewer_board_project_metadata", None, raising=False)


def test_load_state_sets_schema_and_epoch_defaults(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "get_state_issue", lambda: {"body": "queue: []\n"})
    state = reviewer_bot.load_state()
    assert state["schema_version"] == reviewer_bot.STATE_SCHEMA_VERSION
    assert state["freshness_runtime_epoch"] == reviewer_bot.FRESHNESS_RUNTIME_EPOCH_LEGACY


def test_maybe_record_head_observation_repair_wrapper_exports_structured_result_type():
    hints = get_type_hints(reviewer_bot.maybe_record_head_observation_repair)

    assert hints["return"] is reviewer_bot.lifecycle_module.HeadObservationRepairResult


def test_runtime_context_protocol_exposes_structured_head_repair_contract():
    hints = get_type_hints(ReviewerBotContext.maybe_record_head_observation_repair)

    assert hints["return"] is reviewer_bot.lifecycle_module.HeadObservationRepairResult


def test_reconcile_active_review_entry_uses_explicit_head_repair_changed_field(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "refresh_reviewer_review_from_live_preferred_review",
        lambda bot, issue_number, review_data, **kwargs: (False, None),
    )
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )

    message, success, changed = reviewer_bot.reconcile_module.reconcile_active_review_entry(
        reviewer_bot,
        state,
        42,
        require_pull_request_context=True,
    )

    assert success is True
    assert changed is False
    assert "no reconciliation transitions applied" in message


def test_record_conversation_freshness_returns_true_when_only_reviewer_activity_changes(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:100",
        timestamp="2026-03-17T09:00:00Z",
        actor="alice",
    )
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_SOURCE_EVENT_KEY", "issue_comment:100")

    changed = reviewer_bot.comment_routing_module._record_conversation_freshness(
        reviewer_bot,
        state,
        42,
        "alice",
        100,
        "2026-03-17T10:00:00Z",
    )

    assert changed is True
    assert review["last_reviewer_activity"] == "2026-03-17T10:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


def test_handle_pull_request_target_synchronize_returns_true_for_head_only_mutation(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_head_sha"] = "head-1"
    review["contributor_revision"]["seen_keys"] = ["pull_request_sync:42:head-2"]
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("PR_HEAD_SHA", "head-2")
    monkeypatch.setenv("EVENT_CREATED_AT", "2026-03-17T10:00:00Z")

    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data: (None, None),
    )

    assert reviewer_bot.handle_pull_request_target_synchronize(state) is True
    assert review["active_head_sha"] == "head-2"


def test_handle_workflow_run_event_returns_true_for_submitted_review_bookkeeping_only_mutations(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "bob"
    review["deferred_gaps"]["pull_request_review:11"] = {"reason": "artifact_missing"}
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 500,
                "source_run_attempt": 2,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:11",
                "pr_number": 42,
                "review_id": 11,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_record_review_rebuild",
        lambda bot, state_obj, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "maybe_record_head_observation_repair",
        lambda issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/11":
            return {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert "pull_request_review:11" in review["reconciled_source_events"]
    assert "pull_request_review:11" not in review["deferred_gaps"]


def test_handle_workflow_run_event_persists_fail_closed_diagnostic_without_raising(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 501,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:12",
                "pr_number": 42,
                "review_id": 12,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "501")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "pulls/42/reviews/12":
            return reviewer_bot.GitHubApiResult(
                status_code=502,
                payload={"message": "bad gateway"},
                headers={},
                text="bad gateway",
                ok=False,
                failure_kind="server_error",
                retry_attempts=1,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    gap = review["deferred_gaps"]["pull_request_review:12"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"


def test_deferred_comment_reconcile_returns_true_for_bookkeeping_only_mutations(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["deferred_gaps"]["issue_comment:210"] = {"reason": "artifact_missing"}
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /queue"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 610,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:210",
                "pr_number": 42,
                "comment_id": 210,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "610")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(reviewer_bot.reconcile_module, "_handle_command", lambda *args, **kwargs: False)

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/210":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert "issue_comment:210" in review["reconciled_source_events"]
    assert "issue_comment:210" not in review["deferred_gaps"]


def test_repair_visible_review_gap_returns_true_for_bookkeeping_only_mutations(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["deferred_gaps"]["pull_request_review:303"] = {"reason": "artifact_missing"}
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "accept_reviewer_review_from_live_review",
        lambda review_data, live_review, actor=None: False,
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "refresh_reviewer_review_from_live_preferred_review",
        lambda bot, issue_number, review_data, actor=None: (False, None),
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data: (None, None),
    )

    changed = sweeper._repair_visible_review_gap(
        reviewer_bot,
        review,
        42,
        "pull_request_review:303",
        {
            "id": 303,
            "submitted_at": "2026-03-25T11:00:00Z",
            "state": "COMMENTED",
            "commit_id": "head-1",
            "user": {"login": "alice"},
        },
    )

    assert changed is True
    assert "pull_request_review:303" in review["reconciled_source_events"]
    assert "pull_request_review:303" not in review["deferred_gaps"]


def test_get_state_issue_snapshot_uses_retry_aware_read(monkeypatch):
    observed = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["retry_policy"] = kwargs.get("retry_policy")
        return reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"body": "state: ok", "html_url": "https://example.com/state/1"},
            headers={"etag": '"abc"'},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=1,
            transport_error=None,
        )

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)

    snapshot = reviewer_bot.get_state_issue_snapshot()

    assert snapshot is not None
    assert snapshot.etag == '"abc"'
    assert observed["retry_policy"] == "idempotent_read"


def test_conditional_patch_state_issue_sends_if_match_header(monkeypatch):
    observed = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["extra_headers"] = extra_headers
        return reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"body": data["body"]},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        )

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)

    reviewer_bot.conditional_patch_state_issue("updated", '"etag-1"')

    assert observed["extra_headers"] == {"If-Match": '"etag-1"'}


def test_conditional_patch_state_issue_omits_if_match_when_etag_missing(monkeypatch):
    observed = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["extra_headers"] = extra_headers
        return reviewer_bot.GitHubApiResult(200, {"body": data["body"]}, {}, "ok", True, None, 0, None)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)

    reviewer_bot.conditional_patch_state_issue("updated", None)

    assert observed["extra_headers"] is None


def test_ensure_lock_ref_exists_uses_retry_aware_reads(monkeypatch):
    observed = []

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed.append((endpoint, kwargs.get("retry_policy")))
        if endpoint == "git/ref/heads/reviewer-bot-state-lock" and len(observed) == 1:
            return reviewer_bot.GitHubApiResult(
                status_code=404,
                payload={"message": "missing"},
                headers={},
                text="missing",
                ok=False,
                failure_kind="not_found",
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "git/ref/heads/reviewer-bot-state-lock":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"object": {"sha": "base-sha"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "git/ref/heads/main":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"object": {"sha": "base-sha"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=1,
                transport_error=None,
            )
        if endpoint == "git/refs":
            return reviewer_bot.GitHubApiResult(
                status_code=201,
                payload={"ref": "refs/heads/reviewer-bot-state-lock"},
                headers={},
                text="created",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_NAME", "heads/reviewer-bot-state-lock")
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_BOOTSTRAP_BRANCH", "main")

    assert reviewer_bot.ensure_lock_ref_exists() == "base-sha"
    assert observed[0] == ("git/ref/heads/reviewer-bot-state-lock", "idempotent_read")
    assert observed[1] == ("git/ref/heads/main", "idempotent_read")


def test_ensure_lock_ref_exists_fails_closed_when_bootstrap_branch_unavailable(monkeypatch):
    responses = iter(
        [
            reviewer_bot.GitHubApiResult(404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None),
            reviewer_bot.GitHubApiResult(502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None),
        ]
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_NAME", "heads/reviewer-bot-state-lock")
    monkeypatch.setattr(reviewer_bot, "LOCK_REF_BOOTSTRAP_BRANCH", "main")

    with pytest.raises(RuntimeError, match="Unable to read bootstrap branch"):
        reviewer_bot.ensure_lock_ref_exists()


def test_get_lock_ref_snapshot_fails_closed_on_invalid_commit_payload(monkeypatch):
    monkeypatch.setattr(reviewer_bot.lease_lock_module, "ensure_lock_ref_exists", lambda bot: "ref-sha")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"message": "missing tree"},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="missing tree SHA"):
        reviewer_bot.get_lock_ref_snapshot()


def test_save_state_retries_precondition_failed_conflict(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)
    snapshot = reviewer_bot.StateIssueSnapshot(
        body="body",
        etag='"etag"',
        html_url="https://example.com/state/1",
    )
    responses = iter(
        [
            reviewer_bot.GitHubApiResult(412, {"message": "precondition failed"}, {}, "precondition failed", False, None, 0, None),
            reviewer_bot.GitHubApiResult(200, {"body": "updated"}, {}, "ok", True, None, 0, None),
        ]
    )
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", object())
    monkeypatch.setattr(reviewer_bot, "ensure_state_issue_lease_lock_fresh", lambda: True)
    monkeypatch.setattr(reviewer_bot, "get_state_issue_snapshot", lambda: snapshot)
    monkeypatch.setattr(reviewer_bot, "parse_lock_metadata_from_issue_body", lambda body: {})
    monkeypatch.setattr(
        reviewer_bot,
        "render_state_issue_body",
        lambda state_obj, lock_meta, base_body: "updated",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "conditional_patch_state_issue",
        lambda body, etag=None: next(responses),
    )
    monkeypatch.setattr(reviewer_bot.state_store_module.time, "sleep", lambda *_args, **_kwargs: None)

    assert reviewer_bot.save_state(state) is True


def test_renew_state_issue_lease_lock_fails_on_token_mismatch(monkeypatch):
    context = reviewer_bot.LeaseContext(
        lock_token="expected-token",
        lock_owner_run_id="run-1",
        lock_owner_workflow="wf",
        lock_owner_job="job",
        state_issue_url="https://example.com/state/1",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_lock_ref_snapshot",
        lambda: ("ref-sha", "tree-sha", {"lock_token": "different-token", "lock_state": "locked"}),
    )

    assert reviewer_bot.renew_state_issue_lease_lock(context) is False


def test_reviewer_board_preflight_validates_manifest(monkeypatch):
    monkeypatch.setenv("REVIEWER_BOARD_ENABLED", "true")
    monkeypatch.setenv("REVIEWER_BOARD_TOKEN", "board-token")
    monkeypatch.setattr(reviewer_bot, "github_graphql", lambda query, variables=None, *, token=None: valid_reviewer_board_metadata())

    preflight = reviewer_bot.reviewer_board_preflight()

    assert preflight.enabled is True
    assert preflight.valid is True
    assert preflight.project_id == "PVT_kwDOB"


def test_github_api_request_retries_idempotent_get_on_502(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    responses = iter(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"ok": True}, "ok"),
        ]
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1
    assert result.failure_kind is None


def test_github_api_request_retries_transport_exception_for_idempotent_get(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise reviewer_bot.github_api_module.requests.RequestException("timeout")
        return FakeGitHubResponse(200, {"ok": True}, "ok")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"ok": True}
    assert result.retry_attempts == 1


def test_github_api_request_classifies_not_found_without_retry(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        return FakeGitHubResponse(404, {"message": "missing"}, "missing")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "not_found"
    assert result.retry_attempts == 0
    assert calls["count"] == 1


def test_github_api_request_classifies_forbidden_without_retry(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    calls = {"count": 0}

    def fake_request(*args, **kwargs):
        calls["count"] += 1
        return FakeGitHubResponse(403, {"message": "forbidden"}, "forbidden")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True)

    assert result.ok is False
    assert result.failure_kind == "forbidden"
    assert result.retry_attempts == 0
    assert calls["count"] == 1


def test_github_graphql_request_retries_idempotent_query_on_502(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    responses = iter(
        [
            FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
            FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok"),
        ]
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "post", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_graphql_request("query { viewer { login } }", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.payload == {"data": {"viewer": {"login": "bot"}}}
    assert result.retry_attempts == 1


def test_github_api_request_retries_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    responses = iter(
        [
            FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
            FakeGitHubResponse(200, {"ok": True}, "ok"),
        ]
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request("GET", "issues/42", retry_policy="idempotent_read")

    assert result.ok is True
    assert result.retry_attempts == 1


def test_github_api_request_reports_retry_exhaustion_on_repeated_429(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "rate_limited"
    assert result.retry_attempts == reviewer_bot.LOCK_API_RETRY_LIMIT


def test_github_graphql_request_reports_invalid_payload(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "post",
        lambda *args, **kwargs: FakeGitHubResponse(200, ValueError("bad json"), "bad json"),
    )

    result = reviewer_bot.github_graphql_request("query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_graphql_request_reports_graphql_errors(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "post",
        lambda *args, **kwargs: FakeGitHubResponse(
            200, {"errors": [{"message": "boom"}]}, "boom"
        ),
    )

    result = reviewer_bot.github_graphql_request("query { viewer { login } }")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_passes_timeout(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    observed = {}

    def fake_request(method, url, headers=None, json=None, timeout=None):
        observed["timeout"] = timeout
        return FakeGitHubResponse(200, {"ok": True}, "ok")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", fake_request)

    result = reviewer_bot.github_api_request("GET", "issues/42", timeout_seconds=12.5)

    assert result.ok is True
    assert observed["timeout"] == 12.5


def test_github_api_request_rejects_idempotent_retry_for_non_get():
    with pytest.raises(ValueError, match="only valid for REST GET"):
        reviewer_bot.github_api_request("POST", "issues/42", retry_policy="idempotent_read")


def test_github_graphql_request_rejects_idempotent_retry_for_mutation():
    with pytest.raises(ValueError, match="only valid for GraphQL queries"):
        reviewer_bot.github_graphql_request(
            "mutation { closeIssue(input: {}) { clientMutationId } }",
            retry_policy="idempotent_read",
        )


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"COMMENT_USER_TYPE": "Bot", "COMMENT_AUTHOR": "dependabot[bot]"}, "bot_account"),
        ({"COMMENT_USER_TYPE": "User", "COMMENT_AUTHOR": "alice", "COMMENT_INSTALLATION_ID": "7"}, "github_app_or_other_automation"),
        ({"COMMENT_USER_TYPE": "User", "COMMENT_AUTHOR": "alice"}, "repo_user_principal"),
        ({"COMMENT_AUTHOR": "mystery"}, "unknown_actor"),
    ],
)
def test_classify_issue_comment_actor(monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert comment_routing.classify_issue_comment_actor() == expected


def test_classify_comment_payload_distinguishes_command_plus_text():
    payload = comment_routing.classify_comment_payload(reviewer_bot, "hello\n@guidelines-bot /queue")
    assert payload["comment_class"] == "command_plus_text"
    assert payload["has_non_command_text"] is True


def test_route_issue_comment_trust_allows_only_same_repo_repo_user_principal(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "carol"},
        },
    )
    assert comment_routing.route_issue_comment_trust(reviewer_bot, 42) == "pr_trusted_direct"


def test_route_issue_comment_trust_fails_closed_for_ambiguous_same_repo(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("COMMENT_USER_TYPE", "")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "carol"},
        },
    )
    with pytest.raises(RuntimeError, match="Ambiguous same-repo PR comment trust posture"):
        comment_routing.route_issue_comment_trust(reviewer_bot, 42)


def test_handle_non_pr_issue_comment_creates_pending_privileged_command(monkeypatch):
    state = make_state()
    entry = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /accept-no-fls-changes")
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    assert reviewer_bot.handle_comment_event(state) is True
    pending = state["active_reviews"]["42"]["pending_privileged_commands"]
    assert pending["issue_comment:100"]["command_name"] == "accept-no-fls-changes"
    assert pending["issue_comment:100"]["authorization"]["authorized"] is True


def test_closed_non_pr_plain_text_comment_does_not_create_review_entry(monkeypatch):
    state = make_state()
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: close comment")
    assert reviewer_bot.handle_comment_event(state) is False
    assert state["active_reviews"] == {}


def test_closed_non_pr_command_comment_does_not_create_pending_privileged_command(monkeypatch):
    state = make_state()
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /accept-no-fls-changes")
    called = {"post_comment": 0}
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: called.__setitem__("post_comment", called["post_comment"] + 1) or True)
    assert reviewer_bot.handle_comment_event(state) is False
    assert state["active_reviews"] == {}
    assert called["post_comment"] == 0


def test_closed_non_pr_comment_removes_stale_review_entry(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: close comment")
    assert reviewer_bot.handle_comment_event(state) is True
    assert "42" not in state["active_reviews"]


def test_closed_non_pr_comment_without_entry_returns_false(monkeypatch):
    state = make_state()
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "closed")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: close comment")

    assert reviewer_bot.handle_comment_event(state) is False
    assert state["active_reviews"] == {}


def test_open_non_pr_plain_text_comment_still_updates_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_STATE", "open")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "reviewer-bot validation: contributor plain text comment")
    assert reviewer_bot.handle_comment_event(state) is True
    accepted = state["active_reviews"]["42"]["contributor_comment"]["accepted"]
    assert accepted["semantic_key"] == "issue_comment:100"


def test_label_signoff_create_pr_marks_issue_review_complete_without_inline_status_sync(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /label +sign-off: create pr")
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(
        reviewer_bot,
        "sync_status_labels_for_items",
        lambda *args, **kwargs: pytest.fail(
            "status sync should run only from app orchestration after save"
        ),
    )
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append((issue_number, body)) or True)
    assert reviewer_bot.handle_comment_event(state) is True
    assert review["review_completion_source"] == "issue_label: sign-off: create pr"
    assert review["current_cycle_completion"]["completed"] is True
    assert posted == [(42, "✅ Added label `sign-off: create pr`")]


def test_label_signoff_create_pr_on_pr_does_not_mark_issue_complete(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /label +sign-off: create pr")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    monkeypatch.setattr(reviewer_bot, "get_repo_labels", lambda: ["sign-off: create pr"])
    monkeypatch.setattr(reviewer_bot, "add_label", lambda issue_number, label: True)
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda *args, **kwargs: pytest.fail("status sync should not run for PR sign-off label command"))
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda *args, **kwargs: True)
    assert reviewer_bot.handle_comment_event(state) is False
    assert review["review_completion_source"] is None


def test_pr_comment_direct_path_is_epoch_gated(monkeypatch):
    state = make_state(epoch="legacy_v14")
    entry = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert entry is not None
    entry["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "hello")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    assert reviewer_bot.handle_comment_event(state) is False


def test_check_overdue_reviews_skips_transition_after_transition_notice_sent(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_handle_transition_notice_records_transition_notice_sent_at_once(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append((issue_number, body)) or True)
    assert reviewer_bot.handle_transition_notice(state, 42, "alice") is True
    assert review["transition_notice_sent_at"] is not None
    assert reviewer_bot.handle_transition_notice(state, 42, "alice") is False
    assert len(posted) == 1


def test_handle_transition_notice_message_does_not_claim_reassignment(monkeypatch):
    state = make_state()
    reviewer_bot.ensure_review_entry(state, 42, create=True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    assert reviewer_bot.handle_transition_notice(state, 42, "alice") is True
    assert "reassigned to the next person in the queue" not in posted[0]
    assert "/pass" in posted[0]


def test_reviewer_comment_clears_warning_and_transition_notice_markers(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "alice")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "MEMBER")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "hello")
    monkeypatch.setenv("CURRENT_WORKFLOW_FILE", ".github/workflows/reviewer-bot-pr-comment-trusted.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "dana"},
        },
    )
    assert reviewer_bot.handle_comment_event(state) is True
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


def test_scheduled_check_backfills_transition_notice_without_reposting(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    review["transition_warning_sent"] = "2026-03-10T00:00:00Z"
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "check_overdue_reviews",
        lambda bot, state: [
            {
                "issue_number": 42,
                "reviewer": "alice",
                "days_overdue": 20,
                "days_since_warning": 15,
                "needs_warning": False,
                "needs_transition": True,
            }
        ],
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"pull_request": {}})
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)

    def fake_api(method, endpoint, data=None):
        if endpoint == "issues/42/comments?per_page=100":
            return [
                {
                    "id": 99,
                    "created_at": "2026-03-25T15:22:42Z",
                    "body": "🔔 **Transition Period Ended**\n\nExisting notice",
                    "user": {"login": "github-actions[bot]"},
                }
            ]
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_api)
    assert reviewer_bot.handle_scheduled_check(state) is True
    assert review["transition_notice_sent_at"] == "2026-03-25T15:22:42Z"
    assert posted == []


def test_scheduled_check_repairs_missing_reviewer_review_state(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, state: [])
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"pull_request": {}})
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
                {
                    "id": 10,
                    "state": "COMMENTED",
                    "submitted_at": "2026-03-17T10:01:00Z",
                    "commit_id": "head-1",
                    "user": {"login": "alice"},
                }
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )
    assert reviewer_bot.handle_scheduled_check(state) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted is not None
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"


def test_maybe_record_head_observation_repair_skips_unavailable_without_mutation(monkeypatch):
    review_data = {
        "active_head_sha": "head-1",
        "contributor_revision": {"accepted": None},
    }
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result == reviewer_bot.lifecycle_module.HeadObservationRepairResult(
        changed=False,
        outcome="skipped_unavailable",
        failure_kind="server_error",
        reason="pull_request_unavailable",
    )
    assert review_data["active_head_sha"] == "head-1"


def test_maybe_record_head_observation_repair_reports_not_found(monkeypatch):
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=404,
            payload={"message": "missing"},
            headers={},
            text="missing",
            ok=False,
            failure_kind="not_found",
            retry_attempts=0,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "skipped_not_found"
    assert result.failure_kind == "not_found"


def test_maybe_record_head_observation_repair_reports_invalid_payload(monkeypatch):
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"state": "open", "head": {}},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "invalid_live_payload"
    assert result.reason == "pull_request_head_unavailable"


def test_maybe_record_head_observation_repair_skips_not_open(monkeypatch):
    review_data = {"active_head_sha": "head-1", "contributor_revision": {"accepted": None}}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"state": "closed", "head": {"sha": "head-1"}},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "skipped_not_open"


def test_maybe_record_head_observation_repair_records_changed_head_once(monkeypatch):
    review_data = {
        "active_head_sha": "head-1",
        "contributor_revision": {"accepted": None},
        "current_cycle_completion": {"completed": True},
        "current_cycle_write_approval": {"has_write_approval": True},
        "review_completed_at": "2026-03-10T00:00:00Z",
        "review_completed_by": "alice",
        "review_completion_source": "live_review_rebuild",
    }
    accepted = []
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"state": "open", "head": {"sha": "head-2"}},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "accept_channel_event",
        lambda review_data, channel, **kwargs: accepted.append((channel, kwargs)) or True,
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.outcome == "changed"
    assert result.changed is True
    assert review_data["active_head_sha"] == "head-2"
    assert accepted[0][0] == "contributor_revision"
    assert accepted[0][1]["semantic_key"] == "pull_request_head_observed:42:head-2"
    assert review_data["current_cycle_completion"] == {}
    assert review_data["current_cycle_write_approval"] == {}
    assert review_data["review_completed_at"] is None


def test_scheduled_check_records_live_read_failure_and_continues(monkeypatch):
    state = make_state()
    review_42 = reviewer_bot.ensure_review_entry(state, 42, create=True)
    review_43 = reviewer_bot.ensure_review_entry(state, 43, create=True)
    assert review_42 is not None
    assert review_43 is not None
    review_42["current_reviewer"] = "alice"
    review_43["current_reviewer"] = "bob"
    overdue_called = []
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(reviewer_bot, "collect_touched_item", lambda issue_number: None)
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"pull_request": {}})
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, state: overdue_called.append(True) or [])
    monkeypatch.setattr(reviewer_bot.reviews_module, "repair_missing_reviewer_review_state", lambda bot, issue_number, review_data: False)

    def fake_head_repair(bot, issue_number, review_data):
        if issue_number == 42:
            return reviewer_bot.lifecycle_module.HeadObservationRepairResult(
                changed=False,
                outcome="skipped_unavailable",
                failure_kind="server_error",
                reason="pull_request_unavailable",
            )
        review_data["repair_needed"] = {
            "kind": "live_read_failure",
            "phase": "head_observation_repair",
            "reason": "stale",
            "failure_kind": "server_error",
            "recorded_at": "2026-03-01T00:00:00Z",
        }
        return reviewer_bot.lifecycle_module.HeadObservationRepairResult(changed=False, outcome="unchanged")

    monkeypatch.setattr(reviewer_bot.maintenance_module, "maybe_record_head_observation_repair", fake_head_repair)

    assert reviewer_bot.handle_scheduled_check(state) is True
    assert overdue_called == [True]
    assert review_42["repair_needed"]["kind"] == "live_read_failure"
    assert review_42["repair_needed"]["phase"] == "head_observation_repair"
    assert review_42["repair_needed"]["failure_kind"] == "server_error"
    assert review_43["repair_needed"] is None


def test_record_maintenance_repair_marker_ignores_recorded_at_for_identical_failure(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    timestamps = iter(["2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z"])
    monkeypatch.setattr(reviewer_bot.maintenance_module, "_now_iso", lambda bot: next(timestamps))

    first = reviewer_bot.maintenance_module._record_maintenance_repair_marker(
        reviewer_bot,
        review,
        phase="head_observation_repair",
        reason="pull_request_unavailable",
        failure_kind="server_error",
    )
    second = reviewer_bot.maintenance_module._record_maintenance_repair_marker(
        reviewer_bot,
        review,
        phase="head_observation_repair",
        reason="pull_request_unavailable",
        failure_kind="server_error",
    )

    assert first is True
    assert second is False
    assert review["repair_needed"]["recorded_at"] == "2026-03-01T00:00:00Z"


def test_scheduled_check_clears_head_observation_repair_marker_after_success(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["repair_needed"] = {
        "kind": "live_read_failure",
        "phase": "head_observation_repair",
        "reason": "pull_request_unavailable",
        "failure_kind": "server_error",
        "recorded_at": "2026-03-01T00:00:00Z",
    }
    monkeypatch.setattr(reviewer_bot.maintenance_module, "sweep_deferred_gaps", lambda bot, state: False)
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "repair_missing_reviewer_review_state",
        lambda bot, issue_number, review_data: False,
    )
    monkeypatch.setattr(
        reviewer_bot.maintenance_module,
        "maybe_record_head_observation_repair",
        lambda bot, issue_number, review_data: reviewer_bot.lifecycle_module.HeadObservationRepairResult(
            changed=False,
            outcome="unchanged",
        ),
    )
    monkeypatch.setattr(reviewer_bot.maintenance_module, "check_overdue_reviews", lambda bot, state: [])

    assert reviewer_bot.handle_scheduled_check(state) is True
    assert review["repair_needed"] is None


def test_check_overdue_reviews_skips_pr_with_current_head_reviewer_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["active_cycle_started_at"] = "2026-03-01T00:00:00Z"
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": "2026-03-02T00:00:00Z",
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )
    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_check_overdue_reviews_skips_item_when_snapshot_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["last_reviewer_activity"] = "2026-03-01T00:00:00Z"
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: None)

    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_handle_overdue_review_warning_only_records_successful_comment(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: False)

    assert reviewer_bot.maintenance_module.handle_overdue_review_warning(reviewer_bot, state, 42, "alice") is False
    assert review["transition_warning_sent"] is None


def test_remove_label_reports_failure(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=500,
            payload={"message": "boom"},
            headers={},
            text="boom",
            ok=False,
            failure_kind="server_error",
            retry_attempts=0,
            transport_error=None,
        ),
    )

    assert reviewer_bot.remove_label(42, "status: awaiting reviewer response") is False


def test_get_user_permission_status_distinguishes_unavailable(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    assert reviewer_bot.get_user_permission_status("alice", "triage") == "unavailable"
    assert reviewer_bot.check_user_permission("alice", "triage") is None


def test_get_issue_assignees_returns_none_when_fetch_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    assert reviewer_bot.get_issue_assignees(42) is None


def test_handle_issue_or_pr_opened_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps(["coding guideline"]))
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    with pytest.raises(RuntimeError, match="Unable to determine assignees"):
        reviewer_bot.handle_issue_or_pr_opened(state)


def test_check_overdue_reviews_uses_contributor_comment_timestamp_when_turn_returns_to_reviewer(monkeypatch):
    now = reviewer_bot.datetime.now(reviewer_bot.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 20))
    reviewer_review_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 19))
    contributor_comment_at = iso_z(
        now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS, minutes=1)
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = assigned_at
    review["active_cycle_started_at"] = assigned_at
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": reviewer_review_at,
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["contributor_comment"]["accepted"] = {
        "semantic_key": "issue_comment:20",
        "timestamp": contributor_comment_at,
        "actor": "bob",
        "reviewed_head_sha": None,
        "source_precedence": 0,
        "payload": {},
    }
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )
    overdue = reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state)
    assert overdue[0]["issue_number"] == 42
    assert overdue[0]["needs_warning"] is True
    assert overdue[0]["days_overdue"] == 0


def test_check_overdue_reviews_uses_contributor_revision_timestamp_when_head_changes_after_review(monkeypatch):
    now = reviewer_bot.datetime.now(reviewer_bot.timezone.utc)
    assigned_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 20))
    reviewer_review_at = iso_z(now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS + 19))
    contributor_revision_at = iso_z(
        now - timedelta(days=reviewer_bot.REVIEW_DEADLINE_DAYS, minutes=1)
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = assigned_at
    review["active_cycle_started_at"] = assigned_at
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": reviewer_review_at,
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["contributor_revision"]["accepted"] = {
        "semantic_key": "pull_request_sync:42:head-2",
        "timestamp": contributor_revision_at,
        "actor": None,
        "reviewed_head_sha": "head-2",
        "source_precedence": 1,
        "payload": {},
    }
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-2"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    overdue = reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state)
    assert overdue[0]["issue_number"] == 42
    assert overdue[0]["needs_warning"] is True
    assert overdue[0]["days_overdue"] == 0


def test_check_overdue_reviews_ignores_same_head_contributor_revision_after_valid_reviewer_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["active_cycle_started_at"] = "2026-03-01T00:00:00Z"
    review["reviewer_review"]["accepted"] = {
        "semantic_key": "pull_request_review:10",
        "timestamp": "2026-03-02T00:00:00Z",
        "actor": "alice",
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    review["contributor_revision"]["accepted"] = {
        "semantic_key": "pull_request_head_observed:42:head-1",
        "timestamp": "2026-03-12T00:00:00Z",
        "actor": None,
        "reviewed_head_sha": "head-1",
        "source_precedence": 1,
        "payload": {},
    }
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )
    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_issue_edit_by_author_records_contributor_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("SENDER_LOGIN", "dana")
    monkeypatch.setenv("ISSUE_TITLE", "New title")
    monkeypatch.setenv("ISSUE_BODY", "body")
    monkeypatch.setenv("ISSUE_CHANGES_TITLE_FROM", "Old title")
    monkeypatch.setenv("ISSUE_CHANGES_BODY_FROM", "body")
    monkeypatch.setenv("ISSUE_UPDATED_AT", "2026-03-17T10:00:00Z")
    assert reviewer_bot.handle_issue_edited_event(state) is True
    accepted = review["contributor_comment"]["accepted"]
    assert accepted["semantic_key"].startswith("issues_edit_title:42:")


def test_project_status_labels_uses_commit_id_and_comment_freshness(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:1",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-2"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"


def test_project_status_labels_uses_live_current_reviewer_review_when_channel_state_missing(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_preview_board_projection_valid_manifest_yields_preview_output(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "open_tracked_assigned"
    assert preview.eligible is True
    assert preview.desired is not None
    assert preview.desired.review_state == "Awaiting Reviewer"
    assert preview.desired.reviewer == "alice"


def test_preview_board_projection_tracked_unassigned_maps_to_unassigned(monkeypatch):
    state = make_state()
    reviewer_bot.ensure_review_entry(state, 42, create=True)
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "open_tracked_unassigned"
    assert preview.desired is not None
    assert preview.desired.review_state == "Unassigned"
    assert preview.desired.reviewer is None
    assert preview.desired.waiting_since is None
    assert preview.desired.needs_attention == "No"


def test_preview_board_projection_closed_item_maps_to_archive_intent(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "closed", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "closed"
    assert preview.eligible is False
    assert preview.desired is not None
    assert preview.desired.archive is True
    assert preview.desired.ensure_membership is False


def test_preview_board_projection_open_untracked_maps_to_archive_intent(monkeypatch):
    state = make_state()
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.classification == "open_untracked"
    assert preview.eligible is False
    assert preview.desired is not None
    assert preview.desired.archive is True


def test_preview_board_projection_formats_dates_at_day_granularity(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:1",
        timestamp="2026-03-21T08:00:00Z",
        actor="alice",
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-21T08:00:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.desired is not None
    assert preview.desired.assigned_at == "2026-03-20"
    assert preview.desired.waiting_since == "2026-03-21"


def test_project_status_labels_uses_live_review_fallback_for_stale_head(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-2"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "review_head_stale"


def test_project_status_labels_prefers_current_head_review_over_newer_stale_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 11,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:01:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_compute_reviewer_response_state_refreshes_stale_stored_review_from_live_current_head(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_contributor_response"
    assert response_state["reason"] == "completion_missing"
    assert response_state["reviewer_review"]["semantic_key"] == "pull_request_review:10"
    assert response_state["reviewer_review"]["reviewed_head_sha"] == "head-1"


def test_project_status_labels_refreshes_stale_stored_review_from_live_current_head(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_check_overdue_reviews_uses_live_current_head_review_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-01T00:00:00Z"
    review["active_cycle_started_at"] = "2026-03-01T00:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-02T00:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-20T00:00:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-21T00:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "rebuild_pr_approval_state",
        lambda bot, issue_number, review_data, **kwargs: ({"completed": False}, {"has_write_approval": False}),
    )

    assert reviewer_bot.maintenance_module.check_overdue_reviews(reviewer_bot, state) == []


def test_compute_reviewer_response_state_keeps_contributor_handoff_when_stored_review_is_stale(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "contributor_revision",
        semantic_key="pull_request_sync:42:head-1",
        timestamp="2026-03-17T12:00:00Z",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert response_state["reason"] == "contributor_revision_newer"


def test_preview_board_projection_keeps_parity_with_refreshed_live_review_state(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-17T09:00:00Z"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )

    desired_labels, _ = reviewer_bot.project_status_labels_for_item(42, state)
    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert preview.desired is not None
    assert preview.desired.review_state == reviewer_bot.REVIEWER_BOARD_OPTION_AWAITING_CONTRIBUTOR


def test_preview_board_projection_marks_projection_repair_as_attention(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["assigned_at"] = "2026-03-20T12:34:56Z"
    review["active_cycle_started_at"] = "2026-03-20T12:34:56Z"
    review["repair_needed"] = {
        "kind": "projection_failure",
        "reason": "projection_failed",
    }
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": None, "labels": []},
    )

    preview = reviewer_bot.preview_board_projection_for_item(state, 42)

    assert preview.desired is not None
    assert (
        preview.desired.needs_attention
        == reviewer_bot.REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED
    )


def test_project_status_labels_pr256_shape_remains_awaiting_contributor_response(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "vccjgust"
    review["active_cycle_started_at"] = "2026-02-18T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "contributor_comment",
        semantic_key="issue_comment:20",
        timestamp="2026-02-18T09:30:00Z",
        actor="dana",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-current"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 30,
                "state": "COMMENTED",
                "submitted_at": "2026-02-18T10:00:00Z",
                "commit_id": "head-older",
                "user": {"login": "vccjgust"},
            },
            {
                "id": 31,
                "state": "COMMENTED",
                "submitted_at": "2026-02-18T11:00:00Z",
                "commit_id": "head-current",
                "user": {"login": "vccjgust"},
            },
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_CONTRIBUTOR_RESPONSE_LABEL}
    assert metadata["reason"] == "completion_missing"


def test_project_status_labels_prefers_newer_contributor_comment_over_live_review_fallback(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "contributor_comment",
        semantic_key="issue_comment:20",
        timestamp="2026-03-17T10:05:00Z",
        actor="bob",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:01:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_REVIEWER_RESPONSE_LABEL}
    assert metadata["reason"] == "contributor_comment_newer"


def test_record_reviewer_activity_does_not_regress_timestamp_on_legacy_backfill():
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["last_reviewer_activity"] = "2026-03-20T10:00:00Z"
    review["transition_warning_sent"] = "2026-03-21T10:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-22T10:00:00Z"
    reviewer_bot.reviews_module.record_reviewer_activity(review, "2026-03-18T10:00:00Z")
    assert review["last_reviewer_activity"] == "2026-03-20T10:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


def test_project_status_labels_emits_awaiting_write_approval_only_after_completion(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_comment",
        semantic_key="issue_comment:1",
        timestamp="2026-03-17T10:00:00Z",
        actor="alice",
    )
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"state": "open", "head": {"sha": "head-1"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint.startswith("pulls/42/reviews"):
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload=[
                    {
                        "id": 10,
                        "state": "APPROVED",
                        "submitted_at": "2026-03-17T10:01:00Z",
                        "commit_id": "head-1",
                        "user": {"login": "bob"},
                    }
                ],
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "denied")
    desired_labels, metadata = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}
    assert metadata["state"] == "awaiting_write_approval"
    review["mandatory_approver_required"] = True
    desired_labels_again, _ = reviewer_bot.project_status_labels_for_item(42, state)
    assert desired_labels_again == {reviewer_bot.STATUS_AWAITING_WRITE_APPROVAL_LABEL}


def test_compute_reviewer_response_state_reports_pull_request_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_unavailable"


def test_compute_reviewer_response_state_fails_closed_without_stored_activity_when_pr_head_invalid(
    monkeypatch,
):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {}},
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "pull_request_head_unavailable"


def test_compute_reviewer_response_state_reports_permission_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:10",
        timestamp="2026-03-17T10:01:00Z",
        actor="alice",
        reviewed_head_sha="head-1",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"state": "open", "head": {"sha": "head-1"}},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint.startswith("pulls/42/reviews"):
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload=[
                    {
                        "id": 10,
                        "state": "APPROVED",
                        "submitted_at": "2026-03-17T10:01:00Z",
                        "commit_id": "head-1",
                        "user": {"login": "alice"},
                    }
                ],
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "projection_failed"
    assert response_state["reason"] == "permission_unavailable"


def test_list_open_items_with_status_labels_fails_closed_on_unavailable(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="server_error"):
        reviewer_bot.list_open_items_with_status_labels()


def test_handle_workflow_run_event_rebuilds_completion_from_live_review_commit_id(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    payload_path = tmp_path / "deferred.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 500,
                "source_run_attempt": 2,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:11",
                "pr_number": 42,
                "review_id": 11,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "APPROVED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"head": {"sha": "head-2"}},
            "pulls/42/reviews/11": {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "APPROVED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "APPROVED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["current_cycle_completion"]["completed"] is False


def test_repair_missing_reviewer_review_state_refreshes_to_preferred_current_head_review(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"head": {"sha": "head-1"}} if endpoint == "pulls/42" else None,
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T10:00:00Z",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "state": "COMMENTED",
                "submitted_at": "2026-03-17T11:00:00Z",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    assert reviewer_bot.reviews_module.repair_missing_reviewer_review_state(reviewer_bot, 42, review) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"
    assert "pull_request_review:99" in review["reviewer_review"]["seen_keys"]


def test_refresh_reviewer_review_from_live_preferred_review_returns_true_for_activity_only_change(
    monkeypatch,
):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["reviewer_review"] = {
        "accepted": {
            "semantic_key": "pull_request_review:10",
            "timestamp": "2026-03-17T10:01:00Z",
            "actor": "alice",
            "reviewed_head_sha": "head-1",
            "source_precedence": 1,
            "payload": {},
        },
        "seen_keys": ["pull_request_review:10"],
    }
    review["last_reviewer_activity"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
                {
                    "id": 10,
                    "state": "COMMENTED",
                    "submitted_at": "2026-03-17T10:01:00Z",
                    "commit_id": "head-1",
                    "user": {"login": "alice"},
                }
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    changed, preferred_review = reviewer_bot.reviews_module.refresh_reviewer_review_from_live_preferred_review(
        reviewer_bot,
        42,
        review,
    )

    assert changed is True
    assert preferred_review is not None
    assert review["last_reviewer_activity"] == "2026-03-17T10:01:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


def test_compute_reviewer_response_state_is_pure_for_pr_projection(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    before = json.loads(json.dumps(review))
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "state": "open", "pull_request": {}, "labels": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}} if endpoint == "pulls/42" else [],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    response_state = reviewer_bot.compute_reviewer_response_state(42, review)

    assert response_state["state"] == "awaiting_reviewer_response"
    assert review == before


def test_compute_pr_approval_state_result_is_pure(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    before = json.loads(json.dumps(review))
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            {"state": "open", "head": {"sha": "head-1"}}
            if endpoint == "pulls/42"
            else [
                {
                    "id": 10,
                    "state": "APPROVED",
                    "submitted_at": "2026-03-17T10:01:00Z",
                    "commit_id": "head-1",
                    "user": {"login": "alice"},
                }
            ],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="push": "granted")

    result = reviewer_bot.reviews_module.compute_pr_approval_state_result(reviewer_bot, 42, review)

    assert result["ok"] is True
    assert result["completion"]["completed"] is True
    assert review == before


def test_apply_pr_approval_state_mutates_expected_fields():
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None

    reviewer_bot.reviews_module.apply_pr_approval_state(
        review,
        completion={"completed": True, "current_head_sha": "head-1", "qualifying_review_ids": [10]},
        write_approval={"has_write_approval": True, "write_approvers": ["alice"], "current_head_sha": "head-1"},
        current_head_sha="head-1",
    )

    assert review["active_head_sha"] == "head-1"
    assert review["current_cycle_completion"]["completed"] is True
    assert review["current_cycle_write_approval"]["has_write_approval"] is True
    assert review["review_completion_source"] == "live_review_rebuild"


def test_handle_workflow_run_event_refreshes_stale_stored_reviewer_review_to_current_head_preferred_review(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    reviewer_bot.reviews_module.accept_channel_event(
        review,
        "reviewer_review",
        semantic_key="pull_request_review:99",
        timestamp="2026-03-17T11:00:00Z",
        actor="alice",
        reviewed_head_sha="head-0",
        source_precedence=1,
    )
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 500,
                "source_run_attempt": 2,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:99",
                "pr_number": 42,
                "review_id": 99,
                "source_submitted_at": "2026-03-17T11:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-0",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"head": {"sha": "head-1"}, "user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/42/reviews/99":
            return {
                "id": 99,
                "submitted_at": "2026-03-17T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 10,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
            {
                "id": 99,
                "submitted_at": "2026-03-17T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-0",
                "user": {"login": "alice"},
            },
        ],
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    accepted = review["reviewer_review"]["accepted"]
    assert accepted["semantic_key"] == "pull_request_review:10"
    assert accepted["reviewed_head_sha"] == "head-1"


def test_workflow_run_review_submission_clears_warning_and_transition_notice_markers(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    payload_path = tmp_path / "deferred-review.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Submitted Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
                "source_run_id": 500,
                "source_run_attempt": 2,
                "source_event_name": "pull_request_review",
                "source_event_action": "submitted",
                "source_event_key": "pull_request_review:11",
                "pr_number": 42,
                "review_id": 11,
                "source_submitted_at": "2026-03-17T10:00:00Z",
                "source_review_state": "COMMENTED",
                "source_commit_id": "head-1",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Submitted Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "500")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"head": {"sha": "head-2"}, "user": {"login": "dana"}, "labels": []},
            "pulls/42/reviews/11": {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            },
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 11,
                "submitted_at": "2026-03-17T10:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None


def test_deferred_comment_missing_live_object_preserves_source_time_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 501,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:99",
                "pr_number": 42,
                "comment_id": 99,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "501")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: (
            {"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None
        ),
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"]["semantic_key"] == "issue_comment:99"
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:99"]["reason"] == "reconcile_failed_closed"


def test_deferred_review_comment_reconcile_records_contributor_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    live_body = "author reply in review thread"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 701,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:301",
                "pr_number": 42,
                "comment_id": 301,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
                "actor_id": 5,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-701-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "701")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/301":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["contributor_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:301"


def test_deferred_review_comment_reconcile_records_reviewer_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    live_body = "reviewer reply in thread"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 702,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:302",
                "pr_number": 42,
                "comment_id": 302,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T11:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-702-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "702")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "pulls/comments/302":
            return {
                "body": live_body,
                "user": {"login": "alice", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:302"


def test_deferred_review_comment_missing_live_object_preserves_source_time_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 703,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:303",
                "pr_number": 42,
                "comment_id": 303,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-703-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "703")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: ({"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None),
    )
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert review["reviewer_comment"]["accepted"]["semantic_key"] == "pull_request_review_comment:303"
    assert review["deferred_gaps"]["pull_request_review_comment:303"]["reason"] == "reconcile_failed_closed"


def test_review_comment_artifact_identity_validation(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-review-comment.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Review Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
                "source_run_id": 704,
                "source_run_attempt": 1,
                "source_event_name": "pull_request_review_comment",
                "source_event_action": "created",
                "source_event_key": "pull_request_review_comment:304",
                "pr_number": 42,
                "comment_id": 304,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": "abc",
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "alice",
                "actor_id": 6,
                "actor_class": "repo_user_principal",
                "pull_request_review_id": 10,
                "in_reply_to_id": 200,
                "source_artifact_name": "reviewer-bot-review-comment-context-704-attempt-1",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Review Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "704")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    monkeypatch.setattr(reviewer_bot, "github_api", lambda method, endpoint, data=None: {"user": {"login": "dana"}, "labels": []} if endpoint == "pulls/42" else None)
    assert reviewer_bot.handle_workflow_run_event(state) is True


def test_deferred_comment_reconcile_hydrates_pr_author_context_for_contributor_freshness(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    live_body = "reviewer-bot validation: contributor plain text comment"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 601,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:199",
                "pr_number": 42,
                "comment_id": 199,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "601")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": [{"name": "coding guideline"}]}
        if endpoint == "issues/comments/199":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:199"
    assert state["active_reviews"]["42"]["reviewer_comment"]["accepted"] is None
    assert os.environ["IS_PULL_REQUEST"] == "true"
    assert os.environ["ISSUE_AUTHOR"] == "dana"
    assert json.loads(os.environ["ISSUE_LABELS"]) == ["coding guideline"]


def test_deferred_comment_reconcile_uses_pr_assignment_semantics_for_claim(tmp_path, monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "bob", "name": "Bob"}]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /claim"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 602,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:200",
                "pr_number": 42,
                "comment_id": 200,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "602")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    assignment_calls = []
    removed_reviewers = []
    posted_comments = []

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {
                "user": {"login": "dana"},
                "labels": [{"name": "coding guideline"}],
                "requested_reviewers": [{"login": "alice"}],
            }
        if endpoint == "issues/comments/200":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    def fake_request(issue_number, username):
        assignment_calls.append(
            {
                "issue_number": issue_number,
                "username": username,
                "is_pull_request": os.environ.get("IS_PULL_REQUEST"),
                "issue_author": os.environ.get("ISSUE_AUTHOR"),
            }
        )
        return reviewer_bot.AssignmentAttempt(success=True, status_code=201)

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", fake_request)
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda issue_number, username: removed_reviewers.append((issue_number, username)) or True)
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted_comments.append((issue_number, body)) or True)
    monkeypatch.setattr(reviewer_bot, "add_reaction", lambda *args, **kwargs: True)
    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert assignment_calls == [
        {
            "issue_number": 42,
            "username": "bob",
            "is_pull_request": "true",
            "issue_author": "dana",
        }
    ]
    assert removed_reviewers == [(42, "alice")]
    assert state["active_reviews"]["42"]["current_reviewer"] == "bob"
    assert posted_comments


def test_deferred_comment_reconcile_fails_closed_when_command_replay_is_ambiguous(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-command.json"
    live_body = "@guidelines-bot /claim"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 603,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:201",
                "pr_number": 42,
                "comment_id": 201,
                "comment_class": "command_only",
                "has_non_command_text": False,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "bob",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "603")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "issues/comments/201":
            return {
                "body": live_body,
                "user": {"login": "bob", "type": "User"},
                "author_association": "MEMBER",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": body,
        },
    )
    command_calls = []
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "_handle_command",
        lambda *args, **kwargs: command_calls.append("called") or True,
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert command_calls == []
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:201" not in state["active_reviews"]["42"]["reconciled_source_events"]


def test_validate_live_comment_replay_contract_reports_changed_for_command_ambiguity(monkeypatch):
    review = reviewer_bot.ensure_review_entry(make_state(), 42, create=True)
    assert review is not None
    payload = {
        "comment_id": 201,
        "comment_class": "command_only",
        "has_non_command_text": False,
        "source_event_key": "issue_comment:201",
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_created_at": "2026-03-17T10:00:00Z",
        "pr_number": 42,
        "source_run_id": 603,
        "source_run_attempt": 1,
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_artifact_name": "reviewer-bot-comment-context-603-attempt-1",
    }
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_only",
            "has_non_command_text": False,
            "command_count": 2,
            "command": None,
            "args": [],
            "normalized_body": body,
        },
    )

    result = reviewer_bot.reconcile_module._validate_live_comment_replay_contract(
        reviewer_bot,
        review,
        payload,
        "@guidelines-bot /claim",
    )

    assert result.live_classified is None
    assert result.changed is True
    assert result.failed_closed is True
    assert review["deferred_gaps"]["issue_comment:201"]["reason"] == "reconcile_failed_closed"


def test_deferred_comment_reconcile_records_failure_kind_when_live_comment_unavailable(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment-unavailable.json"
    live_body = "reviewer-bot validation: contributor plain text comment"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 603,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:205",
                "pr_number": 42,
                "comment_id": 205,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "603")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        if endpoint == "pulls/42":
            return reviewer_bot.GitHubApiResult(
                status_code=200,
                payload={"user": {"login": "dana"}, "labels": []},
                headers={},
                text="ok",
                ok=True,
                failure_kind=None,
                retry_attempts=0,
                transport_error=None,
            )
        if endpoint == "issues/comments/205":
            return reviewer_bot.GitHubApiResult(
                status_code=502,
                payload={"message": "bad gateway"},
                headers={},
                text="bad gateway",
                ok=False,
                failure_kind="server_error",
                retry_attempts=1,
                transport_error=None,
            )
        raise AssertionError(endpoint)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_github_api_request)

    assert reviewer_bot.handle_workflow_run_event(state) is True
    gap = state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:205"]
    assert gap["reason"] == "reconcile_failed_closed"
    assert gap["failure_kind"] == "server_error"


def test_deferred_comment_reconcile_fails_closed_when_comment_classification_drifts(tmp_path, monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    payload_path = tmp_path / "deferred-comment.json"
    live_body = "reviewer-bot validation: contributor plain text comment"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 604,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:202",
                "pr_number": 42,
                "comment_id": 202,
                "comment_class": "plain_text",
                "has_non_command_text": True,
                "source_body_digest": comment_routing._digest_body(live_body),
                "source_created_at": "2026-03-17T10:00:00Z",
                "actor_login": "dana",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "604")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"user": {"login": "dana"}, "labels": []}
        if endpoint == "issues/comments/202":
            return {
                "body": live_body,
                "user": {"login": "dana", "type": "User"},
                "author_association": "CONTRIBUTOR",
                "performed_via_github_app": None,
            }
        raise AssertionError(f"Unexpected endpoint: {endpoint}")

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(
        reviewer_bot.reconcile_module,
        "classify_comment_payload",
        lambda bot, body: {
            "comment_class": "command_plus_text",
            "has_non_command_text": True,
            "command_count": 1,
            "command": "claim",
            "args": [],
            "normalized_body": body,
        },
    )

    assert reviewer_bot.handle_workflow_run_event(state) is True
    assert state["active_reviews"]["42"]["contributor_comment"]["accepted"]["semantic_key"] == "issue_comment:202"
    assert state["active_reviews"]["42"]["deferred_gaps"]["issue_comment:202"]["reason"] == "reconcile_failed_closed"
    assert "issue_comment:202" not in state["active_reviews"]["42"]["reconciled_source_events"]


def test_observer_noop_payload_is_safe_noop(tmp_path, monkeypatch):
    state = make_state()
    reviewer_bot.ensure_review_entry(state, 42, create=True)
    payload_path = tmp_path / "observer-noop.json"
    payload_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "observer_noop",
                "reason": "ignored_non_human_automation",
                "source_workflow_name": "Reviewer Bot PR Comment Observer",
                "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "source_run_id": 777,
                "source_run_attempt": 1,
                "source_event_name": "issue_comment",
                "source_event_action": "created",
                "source_event_key": "issue_comment:111",
                "pr_number": 42,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFERRED_CONTEXT_PATH", str(payload_path))
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ID", "777")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "1")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    assert reviewer_bot.handle_workflow_run_event(state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_execute_pending_privileged_command_revalidates_live_state(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": reviewer_bot.FLS_AUDIT_LABEL}]},
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "handle_accept_no_fls_changes_command", lambda issue_number, actor: ("ok", True))
    assert reviewer_bot.handle_manual_dispatch(state) is True
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"


def test_execute_pending_privileged_command_hydrates_issue_labels_for_executor(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.delenv("ISSUE_LABELS", raising=False)
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": reviewer_bot.FLS_AUDIT_LABEL}]},
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)

    observed = {}

    def fake_handle(issue_number, actor):
        observed["issue_number"] = issue_number
        observed["actor"] = actor
        observed["issue_labels"] = json.loads(os.environ["ISSUE_LABELS"])
        return ("ok", True)

    monkeypatch.setattr(reviewer_bot, "handle_accept_no_fls_changes_command", fake_handle)
    assert reviewer_bot.handle_manual_dispatch(state) is True
    assert observed == {
        "issue_number": 42,
        "actor": "alice",
        "issue_labels": [reviewer_bot.FLS_AUDIT_LABEL],
    }
    assert review["pending_privileged_commands"]["issue_comment:100"]["status"] == "executed"


def test_execute_pending_privileged_command_fails_closed_without_live_fls_audit_label(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"]["issue_comment:100"] = {
        "source_event_key": "issue_comment:100",
        "command_name": "accept-no-fls-changes",
        "issue_number": 42,
        "actor": "alice",
        "status": "pending",
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": "status: awaiting reviewer response"}]},
    )
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    called = {"handle": 0}
    monkeypatch.setattr(
        reviewer_bot,
        "handle_accept_no_fls_changes_command",
        lambda issue_number, actor: called.__setitem__("handle", called["handle"] + 1) or ("ok", True),
    )
    assert reviewer_bot.handle_manual_dispatch(state) is True
    assert called["handle"] == 0
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result"] == "live_revalidation_failed"


def test_create_pull_request_fails_closed_when_open_pr_lookup_unavailable(monkeypatch):
    called = {"post": 0}
    monkeypatch.setattr(reviewer_bot, "find_open_pr_for_branch_status", lambda branch: ("unavailable", None))
    monkeypatch.setattr(reviewer_bot, "github_api", lambda method, endpoint, data=None: called.__setitem__("post", called["post"] + 1) or None)

    with pytest.raises(RuntimeError, match="Unable to determine whether branch 'feature-branch' already has an open PR"):
        reviewer_bot.create_pull_request("feature-branch", "main", 42)

    assert called["post"] == 0


def test_find_open_pr_for_branch_status_reports_unavailable_for_malformed_payload(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"not": "a list"},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        ),
    )

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("unavailable", None)


def test_find_open_pr_for_branch_status_reports_unavailable_on_transport_failure(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("unavailable", None)


def test_resolve_workflow_run_pr_number_fails_closed_when_pr_unavailable(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_RECONCILE_PR_NUMBER", "42")
    monkeypatch.setenv("WORKFLOW_RUN_RECONCILE_HEAD_SHA", "head-1")
    monkeypatch.setenv("WORKFLOW_RUN_HEAD_SHA", "head-1")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=502,
            payload={"message": "bad gateway"},
            headers={},
            text="bad gateway",
            ok=False,
            failure_kind="server_error",
            retry_attempts=1,
            transport_error=None,
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to fetch pull request #42 during workflow_run reconcile"):
        reviewer_bot.resolve_workflow_run_pr_number()


def test_assign_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "F\u00e9lix Fischer"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_assign_command(state, 42, "@felix91gr")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_assign_command_posts_pr_guidance_on_success(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_assign_command(state, 42, "@felix91gr")
    assert success is True
    assert response == "✅ @felix91gr has been assigned as reviewer."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_claim_command_posts_pr_guidance_on_success(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_claim_command(state, 42, "felix91gr")
    assert success is True
    assert response == "✅ @felix91gr has claimed this review."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_pass_command_posts_pr_guidance_for_new_reviewer(monkeypatch):
    state = make_state()
    state["queue"] = [
        {"github": "alice", "name": "Alice"},
        {"github": "felix91gr", "name": "Félix Fischer"},
    ]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: ["alice"])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    monkeypatch.setattr(reviewer_bot, "unassign_reviewer", lambda issue_number, username: True)
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_pass_command(state, 42, "alice", None)
    assert success is True
    assert "@felix91gr is now assigned as the reviewer." in response
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_assign_from_queue_posts_guidance_only_once(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "felix91gr", "name": "Félix Fischer"}]
    monkeypatch.setenv("IS_PULL_REQUEST", "true")
    monkeypatch.setenv("ISSUE_AUTHOR", "PLeVasseur")
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: [])
    monkeypatch.setattr(reviewer_bot, "request_reviewer_assignment", lambda issue_number, username: reviewer_bot.AssignmentAttempt(success=True, status_code=201))
    posted = []
    monkeypatch.setattr(reviewer_bot, "post_comment", lambda issue_number, body: posted.append(body) or True)
    response, success = reviewer_bot.handle_assign_from_queue_command(state, 42)
    assert success is True
    assert response == "✅ @felix91gr (next in queue) has been assigned as reviewer."
    assert posted == [reviewer_bot.get_pr_guidance("felix91gr", "PLeVasseur")]


def test_list_changed_files_ignores_untracked_bootstrap_noise(monkeypatch, tmp_path):
    commands_seen = []

    def fake_run_command(command, cwd, check=True):
        commands_seen.append(command)
        if command == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if command == ["git", "diff", "--cached", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(reviewer_bot.automation_module, "run_command", fake_run_command)
    assert reviewer_bot.automation_module.list_changed_files(tmp_path) == []
    assert commands_seen == [["git", "diff", "--name-only"], ["git", "diff", "--cached", "--name-only"]]


def test_list_changed_files_reports_tracked_changes_only(monkeypatch, tmp_path):
    def fake_run_command(command, cwd, check=True):
        if command == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="README.md\nsrc/spec.lock\n", stderr="")
        if command == ["git", "diff", "--cached", "--name-only"]:
            return subprocess.CompletedProcess(command, 0, stdout="src/spec.lock\n", stderr="")
        raise AssertionError(f"Unexpected command: {command}")

    monkeypatch.setattr(reviewer_bot.automation_module, "run_command", fake_run_command)
    assert reviewer_bot.automation_module.list_changed_files(tmp_path) == ["README.md", "src/spec.lock"]


def test_privileged_commands_workflow_executes_source_entrypoint():
    workflow_text = Path(".github/workflows/reviewer-bot-privileged-commands.yml").read_text(encoding="utf-8")
    assert "Fetch trusted bot source tarball" in workflow_text
    assert 'REVIEWER_BOT_TARGET_REPO_ROOT: ${{ github.workspace }}' in workflow_text
    assert 'run: uv run --project "$BOT_SRC_ROOT" python "$BOT_SRC_ROOT/scripts/reviewer_bot.py"' in workflow_text


def test_accept_no_fls_changes_honors_explicit_target_repo_root(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWER_BOT_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    observed = {"cwd": None}

    def fake_list_changed_files(repo_root):
        observed["cwd"] = repo_root
        return ["README.md"]

    monkeypatch.setattr(reviewer_bot, "list_changed_files", fake_list_changed_files)
    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")
    assert (message, success) == ("❌ Working tree is not clean; refusing to update spec.lock.", False)
    assert observed["cwd"] == tmp_path


def test_accept_no_fls_changes_uses_locked_nested_uv_commands(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWER_BOT_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    list_calls = {"count": 0}

    def fake_list_changed_files(repo_root):
        list_calls["count"] += 1
        assert repo_root == tmp_path
        return []

    commands = []

    def fake_run_command(command, cwd, check=False):
        commands.append((command, cwd, check))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(reviewer_bot, "list_changed_files", fake_list_changed_files)
    monkeypatch.setattr(reviewer_bot, "run_command", fake_run_command)
    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")
    assert (message, success) == ("✅ `src/spec.lock` is already up to date; no PR needed.", True)
    assert list_calls["count"] == 2
    assert commands == [
        (["uv", "run", "--locked", "python", "scripts/fls_audit.py", "--summary-only", "--fail-on-impact"], tmp_path, False),
        (["uv", "run", "--locked", "python", "./make.py", "--update-spec-lock-file"], tmp_path, False),
    ]


def test_accept_no_fls_changes_surfaces_locked_uv_failure_details(monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWER_BOT_TARGET_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "check_user_permission", lambda username, required_permission="triage": True)
    monkeypatch.setattr(reviewer_bot, "list_changed_files", lambda repo_root: [])

    def fake_run_command(command, cwd, check=False):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="error: lockfile at uv.lock needs to be updated, but --locked was provided",
        )

    monkeypatch.setattr(reviewer_bot, "run_command", fake_run_command)
    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")
    assert success is False
    assert "Audit command failed." in message
    assert "--locked was provided" in message


def test_update_spec_lock_file_mode_exits_before_build_docs(monkeypatch, tmp_path):
    monkeypatch.setattr(build_cli.argparse.ArgumentParser, "parse_args", lambda self: type("Args", (), {
        "clear": False,
        "offline": False,
        "ignore_spec_lock_diff": False,
        "update_spec_lock_file": True,
        "validate_urls": False,
        "serve": False,
        "check_links": False,
        "xml": False,
        "verbose": False,
        "debug": False,
    })())
    called = {"update": 0, "build": 0}
    monkeypatch.setattr(build_cli, "update_spec_lockfile", lambda url, path: called.__setitem__("update", called["update"] + 1) or True)
    monkeypatch.setattr(build_cli, "build_docs", lambda *args, **kwargs: called.__setitem__("build", called["build"] + 1))
    with pytest.raises(SystemExit) as exc_info:
        build_cli.main(tmp_path)
    assert exc_info.value.code == 0
    assert called == {"update": 1, "build": 0}


def test_observer_run_reason_mapping_and_near_miss_signature():
    signature = {"status": "waiting", "conclusion": None, "name": "approval_pending"}
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "approval_pending"}, signature) == "awaiting_observer_approval"
    assert sweeper.observer_run_reason_from_details({"status": "waiting", "conclusion": None, "name": "almost"}, signature) == "observer_state_unknown"


def test_negative_missing_run_requires_full_scan_and_recheck():
    gap = {
        "source_event_created_at": "2026-03-15T00:00:00Z",
        "full_scan_complete": True,
        "later_recheck_complete": True,
        "correlated_run_found": False,
        "approval_pending_evidence_retained": False,
    }
    assert sweeper.can_mark_observer_run_missing(gap) is True
    gap["later_recheck_complete"] = False
    assert sweeper.can_mark_observer_run_missing(gap) is False


def test_stage_a_candidate_run_correlation_is_exact_to_workflow_event_pr_and_window():
    os.environ["GITHUB_REPOSITORY"] = "rustfoundation/safety-critical-rust-coding-guidelines"
    result = sweeper.correlate_candidate_observer_runs(
        "issue_comment:101",
        source_event_kind="issue_comment:created",
        source_event_created_at="2026-03-17T10:00:00Z",
        pr_number=42,
        workflow_file=".github/workflows/reviewer-bot-pr-comment-observer.yml",
        workflow_runs=[
            {
                "id": 1,
                "event": "issue_comment",
                "path": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "created_at": "2026-03-17T10:05:00Z",
                "repository": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"},
                "pull_requests": [{"number": 42}],
            },
            {
                "id": 2,
                "event": "issue_comment",
                "path": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
                "created_at": "2026-03-17T10:40:00Z",
                "repository": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"},
                "pull_requests": [{"number": 42}],
            },
        ],
    )
    assert result["candidate_run_ids"] == [1]


def test_stage_b_artifact_correlation_rejects_ambiguous_exact_matches():
    result = sweeper.correlate_run_artifacts_exact(
        {
            10: [{"source_event_key": "issue_comment:101", "source_run_id": 10, "source_run_attempt": 1, "pr_number": 42}],
            11: [{"source_event_key": "issue_comment:101", "source_run_id": 11, "source_run_attempt": 1, "pr_number": 42}],
        },
        "issue_comment:101",
        pr_number=42,
    )
    assert result["status"] == "observer_state_unknown"
    assert result["reason"] == "ambiguous_exact_artifact_matches"


def test_list_run_artifacts_consumes_retry_aware_success(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, **kwargs: reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"artifacts": [{"id": 1, "name": "artifact"}]},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=1,
            transport_error=None,
        ),
    )

    assert sweeper._list_run_artifacts(reviewer_bot, 10) == [{"id": 1, "name": "artifact"}]


def test_evaluate_gap_state_treats_artifact_download_unavailable_as_unknown():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "artifact_scan_outcomes": {10: "download_unavailable"}},
    )
    assert reason == "observer_state_unknown"
    assert diagnostic == "artifact_download_unavailable"


def test_evaluate_gap_state_only_emits_missing_after_negative_inference_contract():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {
            "source_event_created_at": "2026-03-15T00:00:00Z",
            "full_scan_complete": True,
            "later_recheck_complete": True,
            "correlated_run_found": False,
            "approval_pending_evidence_retained": False,
        },
        {
            "status": "no_candidate_runs",
            "full_scan_complete": True,
            "later_recheck_complete": True,
            "correlated_run": None,
        },
        None,
        None,
    )
    assert reason == "observer_run_missing"
    assert diagnostic == "negative_inference_satisfied"


def test_evaluate_gap_state_completed_success_without_exact_artifact_is_artifact_missing():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "reason": "no_exact_source_event_key_match"},
    )
    assert reason == "artifact_missing"
    assert diagnostic == "no_exact_source_event_key_match"


def test_evaluate_gap_state_completed_success_with_expired_artifact_marks_artifact_expired():
    reason, diagnostic = sweeper.evaluate_deferred_gap_state(
        {"source_event_created_at": "2026-03-17T00:00:00Z"},
        {"status": "candidate_runs_found", "correlated_run": 10},
        {"status": "completed", "conclusion": "success"},
        {"status": "no_exact_artifact_match", "artifact_scan_outcomes": {10: "expired"}},
    )
    assert reason == "artifact_expired"
    assert diagnostic == "prior_visibility_or_retention_proof_required"


def test_artifact_gap_reason_requires_prior_visibility_or_documented_retention():
    expired = {
        "artifact_seen_at": "2026-03-10T00:00:00Z",
        "run_created_at": "2026-03-10T00:00:00Z",
    }
    assert sweeper.classify_artifact_gap_reason(expired) == "artifact_expired"
    missing = {
        "artifact_inspection_complete": True,
        "run_created_at": "2026-03-17T00:00:00Z",
    }
    assert sweeper.classify_artifact_gap_reason(missing) == "artifact_missing"


def test_discover_visible_comment_events_skips_github_actions_and_bot_comments(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: [
            {
                "id": 100,
                "created_at": "2026-03-25T10:00:00Z",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
            {
                "id": 101,
                "created_at": "2026-03-25T11:00:00Z",
                "user": {"login": "alice", "type": "User"},
            },
        ],
    )
    discovered, complete = sweeper._discover_visible_comment_events(reviewer_bot, 42, review)
    assert complete is True
    assert [item["source_event_key"] for item in discovered] == ["issue_comment:101"]


def test_sweeper_creates_keyed_deferred_gaps_for_visible_comments_reviews_and_dismissals(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-25T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
                {"id": 202, "submitted_at": "2026-03-25T11:00:00Z", "state": "APPROVED"},
                {"id": 303, "submitted_at": "2026-03-25T09:00:00Z", "updated_at": "2026-03-25T12:00:00Z", "state": "DISMISSED"},
        ],
    )
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "issue_comment:101" in gaps
    assert "pull_request_review:202" in gaps
    assert "pull_request_review_dismissed:303" in gaps
    assert gaps["pull_request_review_dismissed:303"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"


def test_sweeper_creates_keyed_deferred_gap_for_visible_review_comments(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"state": "open", "head": {"sha": "head-1"}}
        if endpoint == "issues/42/comments?per_page=100&page=1":
            return []
        if endpoint == "pulls/42/comments?per_page=100":
            return [{"id": 404, "created_at": "2026-03-25T10:30:00Z", "user": {"login": "dana", "type": "User"}}]
        if endpoint.startswith("actions/workflows/"):
            return {"workflow_runs": []}
        return None

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "pull_request_review_comment:404" in gaps
    assert gaps["pull_request_review_comment:404"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-comment-observer.yml"


def test_sweeper_skips_dismissed_reviews_already_reconciled_by_source_event_key(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["pull_request_review_dismissed:303"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 303, "submitted_at": "2026-03-17T09:00:00Z", "updated_at": "2026-03-17T12:00:00Z", "state": "DISMISSED"},
        ],
    )
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_sweeper_skips_events_already_reconciled_by_source_event_key(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["issue_comment:101", "pull_request_review:202"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-17T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [{"id": 202, "submitted_at": "2026-03-17T11:00:00Z", "state": "APPROVED"}])
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_sweeper_fetches_single_candidate_run_detail_without_exact_artifact_match(monkeypatch):
    run_correlation = {
        "candidate_run_ids": [123],
        "correlated_run": None,
        "correlated_run_found": False,
    }
    monkeypatch.setattr(sweeper, "_fetch_run_detail", lambda bot, run_id: {"id": run_id, "status": "completed", "conclusion": "action_required"})
    detail = sweeper._maybe_fetch_single_candidate_run_detail(reviewer_bot, run_correlation, {"status": "no_exact_artifact_match"})
    assert detail == {"id": 123, "status": "completed", "conclusion": "action_required"}
    assert run_correlation["correlated_run"] == 123


def test_sweeper_visible_review_repair_refreshes_current_reviewer_activity_without_artifact(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["active_cycle_started_at"] = "2026-03-17T09:00:00Z"
    review["transition_warning_sent"] = "2026-03-18T00:00:00Z"
    review["transition_notice_sent_at"] = "2026-03-25T00:00:00Z"
    review["deferred_gaps"]["pull_request_review:202"] = {"reason": "artifact_missing"}
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"state": "open", "head": {"sha": "head-1"}} if endpoint == "pulls/42" else {"workflow_runs": []},
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {
                "id": 202,
                "submitted_at": "2026-03-25T11:00:00Z",
                "state": "COMMENTED",
                "commit_id": "head-1",
                "user": {"login": "alice"},
            }
        ],
    )
    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    assert review["last_reviewer_activity"] == "2026-03-25T11:00:00Z"
    assert review["transition_warning_sent"] is None
    assert review["transition_notice_sent_at"] is None
    assert "pull_request_review:202" not in review["deferred_gaps"]
    assert "pull_request_review:202" in review["reconciled_source_events"]


def test_workflow_policy_split_and_lock_only_boundaries():
    workflows_dir = Path(".github/workflows")
    required = {
        "reviewer-bot-issues.yml",
        "reviewer-bot-issue-comment-direct.yml",
        "reviewer-bot-sweeper-repair.yml",
        "reviewer-bot-pr-metadata.yml",
        "reviewer-bot-pr-comment-trusted.yml",
        "reviewer-bot-pr-comment-observer.yml",
        "reviewer-bot-pr-review-submitted-observer.yml",
        "reviewer-bot-pr-review-dismissed-observer.yml",
        "reviewer-bot-pr-review-comment-observer.yml",
        "reviewer-bot-reconcile.yml",
        "reviewer-bot-privileged-commands.yml",
    }
    assert required.issubset({path.name for path in workflows_dir.glob("reviewer-bot-*.yml")})
    for path in required:
        data = yaml.safe_load((workflows_dir / path).read_text(encoding="utf-8"))
        jobs = data.get("jobs", {})
        for job in jobs.values():
            permissions = job.get("permissions", {})
            steps = job.get("steps", [])
            uses_values = [step.get("uses", "") for step in steps if isinstance(step, dict)]
            text = (workflows_dir / path).read_text(encoding="utf-8")
            if "observer" in path:
                assert permissions.get("contents") == "read"
                assert all("checkout" not in value for value in uses_values)
            if permissions.get("contents") == "write" and path != "reviewer-bot-privileged-commands.yml":
                assert all("checkout" not in value for value in uses_values)
                assert "Temporary lock debt" in text
            for value in uses_values:
                if value:
                    assert "@" in value and len(value.split("@", 1)[1]) == 40


def test_sweeper_repair_workflow_exposes_reviewer_board_preview_dispatch():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8"))
    on_block = data.get("on", data.get(True))
    workflow_dispatch = on_block["workflow_dispatch"]
    action_input = workflow_dispatch["inputs"]["action"]
    assert "preview-reviewer-board" in action_input["options"]
    issue_number_input = workflow_dispatch["inputs"]["issue_number"]
    assert issue_number_input["required"] is False
    assert issue_number_input["type"] == "string"


def test_sweeper_repair_workflow_scopes_reviewer_board_env_to_preview_only():
    workflow_text = Path(".github/workflows/reviewer-bot-sweeper-repair.yml").read_text(encoding="utf-8")
    assert "ISSUE_NUMBER: ${{ github.event.inputs.issue_number }}" in workflow_text
    assert (
        "REVIEWER_BOARD_ENABLED: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && 'true' || 'false' }}"
        in workflow_text
    )
    assert (
        "REVIEWER_BOARD_TOKEN: ${{ github.event_name == 'workflow_dispatch' && github.event.inputs.action == 'preview-reviewer-board' && secrets.REVIEWER_BOARD_TOKEN || '' }}"
        in workflow_text
    )


def test_pr_comment_observer_workflow_builds_payload_inline_without_bot_src_root():
    workflow = Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8")
    assert "BOT_SRC_ROOT" not in workflow
    assert "build_pr_comment_observer_payload" not in workflow
    assert "Fetch trusted bot source tarball" not in workflow


def test_workflow_summaries_and_runbook_references_exist():
    runbook = Path("docs/reviewer-bot-review-freshness-operator-runbook.md")
    assert runbook.exists()
    reconcile = Path(".github/workflows/reviewer-bot-reconcile.yml").read_text(encoding="utf-8")
    assert "docs/reviewer-bot-review-freshness-operator-runbook.md" in reconcile


def test_trusted_pr_comment_workflow_preflights_same_repo_before_mutation():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-trusted.yml").read_text(encoding="utf-8"))
    job = data["jobs"]["reviewer-bot-pr-comment-trusted"]
    steps = job["steps"]
    assert steps[0]["name"] == "Decide whether same-repo trusted path applies"
    assert steps[1]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[2]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[3]["if"] == "env.RUN_TRUSTED_PR_COMMENT == 'true'"
    assert steps[4]["name"] == "Trusted path skipped"
    assert steps[4]["if"] == "env.RUN_TRUSTED_PR_COMMENT != 'true'"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-comment-trusted.yml").read_text(encoding="utf-8")
    assert "https://api.github.com/repos/{repo}/pulls/{pr_number}" in workflow_text
    assert "RUN_TRUSTED_PR_COMMENT" in workflow_text


def test_pr_comment_observer_workflow_uses_inline_payload_builder():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8"))
    job = data["jobs"]["observer"]
    steps = job["steps"]
    assert steps[0]["name"] == "Build deferred comment artifact"
    assert steps[1]["name"] == "Upload deferred comment artifact"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-comment-observer.yml").read_text(encoding="utf-8")
    assert "build_pr_comment_observer_payload" not in workflow_text
    assert 'uv run --project "$BOT_SRC_ROOT"' not in workflow_text


def test_review_comment_observer_workflow_exists_and_is_read_only():
    data = yaml.safe_load(Path(".github/workflows/reviewer-bot-pr-review-comment-observer.yml").read_text(encoding="utf-8"))
    on_block = data.get("on", data.get(True))
    assert on_block["pull_request_review_comment"]["types"] == ["created"]
    job = data["jobs"]["observer"]
    assert job["permissions"]["contents"] == "read"
    steps = job["steps"]
    assert steps[0]["name"] == "Build deferred review comment artifact"
    assert steps[1]["name"] == "Upload deferred review comment artifact"
    workflow_text = Path(".github/workflows/reviewer-bot-pr-review-comment-observer.yml").read_text(encoding="utf-8")
    assert "checkout" not in workflow_text
    assert "pull_request_review_comment" in workflow_text


def test_build_pr_comment_observer_payload_marks_trusted_direct_same_repo_as_observer_noop(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "rustfoundation/safety-critical-rust-coding-guidelines")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "PLeVasseur")
    monkeypatch.setenv("COMMENT_AUTHOR_ASSOCIATION", "COLLABORATOR")
    monkeypatch.setenv("COMMENT_SENDER_TYPE", "User")
    monkeypatch.setenv("COMMENT_INSTALLATION_ID", "")
    monkeypatch.setenv("COMMENT_PERFORMED_VIA_GITHUB_APP", "false")
    monkeypatch.setenv("COMMENT_BODY", "@guidelines-bot /r? @felix91gr")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_AUTHOR_ID", "123")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-20T20:48:25Z")
    monkeypatch.setenv("GITHUB_RUN_ID", "999")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "head": {"repo": {"full_name": "rustfoundation/safety-critical-rust-coding-guidelines"}},
            "user": {"login": "PLeVasseur"},
        },
    )
    payload = reviewer_bot.build_pr_comment_observer_payload(42)
    assert payload["kind"] == "observer_noop"
    assert payload["reason"] == "trusted_direct_same_repo_human_comment"
    assert payload["source_event_key"] == "issue_comment:100"


def test_issue_comment_direct_workflow_exports_issue_state():
    workflow_text = Path(".github/workflows/reviewer-bot-issue-comment-direct.yml").read_text(encoding="utf-8")
    assert "ISSUE_STATE: ${{ github.event.issue.state }}" in workflow_text


def test_mutating_reviewer_bot_workflows_do_not_share_global_github_concurrency():
    workflow_paths = [
        ".github/workflows/reviewer-bot-issues.yml",
        ".github/workflows/reviewer-bot-issue-comment-direct.yml",
        ".github/workflows/reviewer-bot-sweeper-repair.yml",
        ".github/workflows/reviewer-bot-pr-metadata.yml",
        ".github/workflows/reviewer-bot-pr-comment-trusted.yml",
        ".github/workflows/reviewer-bot-reconcile.yml",
        ".github/workflows/reviewer-bot-privileged-commands.yml",
    ]
    for workflow_path in workflow_paths:
        data = yaml.safe_load(Path(workflow_path).read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            assert "concurrency" not in job


def test_github_api_request_reports_invalid_payload_for_malformed_json(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(200, ValueError("bad json"), "bad json"),
    )

    result = reviewer_bot.github_api_request("GET", "issues/42")

    assert result.ok is False
    assert result.failure_kind == "invalid_payload"


def test_github_api_request_reports_retry_exhaustion_on_repeated_502(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")
    monkeypatch.setattr(
        reviewer_bot.github_api_module.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(502, {"message": "bad gateway"}, "bad gateway"),
    )
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "server_error"
    assert result.retry_attempts == reviewer_bot.LOCK_API_RETRY_LIMIT


def test_github_api_request_reports_transport_retry_exhaustion(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setenv("REPO_NAME", "safety-critical-rust-coding-guidelines")

    def always_fail(*args, **kwargs):
        raise reviewer_bot.github_api_module.requests.RequestException("timeout")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "request", always_fail)
    monkeypatch.setattr(reviewer_bot.github_api_module.time, "sleep", lambda *_args, **_kwargs: None)

    result = reviewer_bot.github_api_request(
        "GET", "issues/42", retry_policy="idempotent_read", suppress_error_log=True
    )

    assert result.ok is False
    assert result.failure_kind == "transport_error"
    assert result.retry_attempts == reviewer_bot.LOCK_API_RETRY_LIMIT
    assert "timeout" in str(result.transport_error)


def test_github_graphql_request_passes_timeout(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    observed = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        observed["timeout"] = timeout
        return FakeGitHubResponse(200, {"data": {"viewer": {"login": "bot"}}}, "ok")

    monkeypatch.setattr(reviewer_bot.github_api_module.requests, "post", fake_post)

    result = reviewer_bot.github_graphql_request(
        "query { viewer { login } }", timeout_seconds=9.5
    )

    assert result.ok is True
    assert observed["timeout"] == 9.5


def test_maybe_record_head_observation_repair_uses_github_api_fallback_after_system_exit(monkeypatch):
    review_data = {
        "active_head_sha": "head-0",
        "contributor_revision": {"accepted": None},
    }
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {"state": "open", "head": {"sha": "head-1"}},
    )
    monkeypatch.setattr(
        reviewer_bot.reviews_module,
        "accept_channel_event",
        lambda review_data, channel, **kwargs: True,
    )

    result = reviewer_bot.maybe_record_head_observation_repair(42, review_data)

    assert result.changed is True
    assert result.outcome == "changed"
    assert review_data["active_head_sha"] == "head-1"


def test_find_open_pr_for_branch_status_blank_owner_or_branch_is_not_found(monkeypatch):
    monkeypatch.delenv("REPO_OWNER", raising=False)

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("not_found", None)
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    assert reviewer_bot.find_open_pr_for_branch_status("") == ("not_found", None)


def test_find_open_pr_for_branch_status_reports_found(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200,
            [{"number": 42, "html_url": "https://example.com/pr/42"}],
            {},
            "ok",
            True,
            None,
            0,
            None,
        ),
    )

    status, pr = reviewer_bot.find_open_pr_for_branch_status("feature")

    assert status == "found"
    assert pr == {"number": 42, "html_url": "https://example.com/pr/42"}


def test_find_open_pr_for_branch_status_reports_not_found_for_empty_payload(monkeypatch):
    monkeypatch.setenv("REPO_OWNER", "rustfoundation")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, [], {}, "ok", True, None, 0, None
        ),
    )

    assert reviewer_bot.find_open_pr_for_branch_status("feature") == ("not_found", None)


def test_handle_accept_no_fls_changes_command_fails_closed_when_permission_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_LABELS", json.dumps([reviewer_bot.FLS_AUDIT_LABEL]))
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    message, success = reviewer_bot.handle_accept_no_fls_changes_command(42, "alice")

    assert success is False
    assert "Unable to verify triage permissions right now" in message


def test_pass_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_pass_command(state, 42, "alice", None)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_away_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}, {"github": "bob", "name": "Bob"}]
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_pass_until_command(
        state,
        42,
        "alice",
        "2099-01-01",
        None,
    )

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_claim_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_claim_command(state, 42, "alice")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_release_command_fails_closed_when_permission_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    response, success = reviewer_bot.handle_release_command(state, 42, "alice", ["@bob"])

    assert success is False
    assert "Unable to verify triage permissions right now" in response


def test_release_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_release_command(state, 42, "alice")

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_assign_from_queue_command_fails_closed_when_assignees_unavailable(monkeypatch):
    state = make_state()
    state["queue"] = [{"github": "alice", "name": "Alice"}]
    monkeypatch.setattr(reviewer_bot, "get_issue_assignees", lambda issue_number: None)

    response, success = reviewer_bot.handle_assign_from_queue_command(state, 42)

    assert success is False
    assert "Unable to determine current assignees/reviewers" in response


def test_handle_rectify_command_reports_permission_unavailable(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "ensure_review_entry", lambda current, issue_number: None)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    message, success, changed = reviewer_bot.handle_rectify_command(state, 42, "alice")

    assert success is False
    assert changed is False
    assert "Unable to verify triage permissions right now" in message


def test_handle_rectify_command_reports_permission_denied(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "ensure_review_entry", lambda current, issue_number: None)
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "denied")

    message, success, changed = reviewer_bot.handle_rectify_command(state, 42, "alice")

    assert success is False
    assert changed is False
    assert "Only maintainers with triage+ permission" in message


def test_validate_accept_no_fls_changes_handoff_distinguishes_permission_unavailable(monkeypatch):
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setattr(reviewer_bot, "parse_issue_labels", lambda: [reviewer_bot.FLS_AUDIT_LABEL])
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    ok, metadata = comment_routing._validate_accept_no_fls_changes_handoff(
        reviewer_bot,
        42,
        "alice",
    )

    assert ok is False
    assert metadata["reason"] == "authorization_unavailable"


def test_manual_dispatch_marks_live_permission_unavailable_for_pending_privileged_command(monkeypatch):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["pending_privileged_commands"] = {
        "issue_comment:100": {
            "source_event_key": "issue_comment:100",
            "command_name": "accept-no-fls-changes",
            "issue_number": 42,
            "actor": "alice",
            "status": "pending",
        }
    }
    monkeypatch.setenv("MANUAL_ACTION", "execute-pending-privileged-command")
    monkeypatch.setenv("PRIVILEGED_SOURCE_EVENT_KEY", "issue_comment:100")
    monkeypatch.setattr(
        reviewer_bot,
        "get_issue_or_pr_snapshot",
        lambda issue_number: {"number": issue_number, "labels": [{"name": reviewer_bot.FLS_AUDIT_LABEL}]},
    )
    monkeypatch.setattr(reviewer_bot, "get_user_permission_status", lambda username, required_permission="triage": "unavailable")

    assert reviewer_bot.handle_manual_dispatch(state) is True
    pending = review["pending_privileged_commands"]["issue_comment:100"]
    assert pending["status"] == "failed_closed"
    assert pending["result"] == "live_permission_unavailable"


def test_get_pull_request_reviews_result_paginates(monkeypatch):
    responses = {
        "pulls/42/reviews?per_page=100&page=1": reviewer_bot.GitHubApiResult(200, [{"id": i} for i in range(100)], {}, "ok", True, None, 0, None),
        "pulls/42/reviews?per_page=100&page=2": reviewer_bot.GitHubApiResult(200, [{"id": 100}], {}, "ok", True, None, 0, None),
    }
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: responses[endpoint],
    )

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result["ok"] is True
    assert len(result["reviews"]) == 101


def test_get_pull_request_reviews_result_uses_fallback_loader_after_system_exit(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: (_ for _ in ()).throw(SystemExit(1)))
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [{"id": 10}])

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": True, "reviews": [{"id": 10}]}


def test_get_pull_request_reviews_result_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, {"not": "a list"}, {}, "ok", True, None, 0, None
        ),
    )

    result = reviewer_bot.reviews_module.get_pull_request_reviews_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "reviews_unavailable", "failure_kind": "invalid_payload"}


def test_pull_request_read_result_reports_not_found(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None
        ),
    )

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_not_found", "failure_kind": "not_found"}


def test_pull_request_read_result_reports_invalid_payload(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda method, endpoint, data=None, extra_headers=None, **kwargs: reviewer_bot.GitHubApiResult(
            200, ["not", "a", "dict"], {}, "ok", True, None, 0, None
        ),
    )

    result = reviewer_bot.reviews_module._pull_request_read_result(reviewer_bot, 42)

    assert result == {"ok": False, "reason": "pull_request_unavailable", "failure_kind": "invalid_payload"}


def test_ensure_lock_ref_exists_fails_closed_when_lock_ref_read_remains_unavailable(monkeypatch):
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: reviewer_bot.GitHubApiResult(
            502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to read reviewer-bot lock ref"):
        reviewer_bot.ensure_lock_ref_exists()


def test_ensure_lock_ref_exists_fails_closed_when_bootstrap_branch_sha_missing(monkeypatch):
    responses = iter(
        [
            reviewer_bot.GitHubApiResult(404, {"message": "missing"}, {}, "missing", False, "not_found", 0, None),
            reviewer_bot.GitHubApiResult(200, {"object": {}}, {}, "ok", True, None, 0, None),
        ]
    )
    monkeypatch.setattr(reviewer_bot, "github_api_request", lambda *args, **kwargs: next(responses))

    with pytest.raises(RuntimeError, match="Bootstrap branch ref did not include SHA"):
        reviewer_bot.ensure_lock_ref_exists()


def test_get_lock_ref_snapshot_fails_closed_when_commit_fetch_unavailable(monkeypatch):
    monkeypatch.setattr(reviewer_bot.lease_lock_module, "ensure_lock_ref_exists", lambda bot: "ref-sha")
    monkeypatch.setattr(
        reviewer_bot,
        "github_api_request",
        lambda *args, **kwargs: reviewer_bot.GitHubApiResult(
            502, {"message": "bad gateway"}, {}, "bad gateway", False, "server_error", 1, None
        ),
    )

    with pytest.raises(RuntimeError, match="Failed to read lock commit"):
        reviewer_bot.get_lock_ref_snapshot()


def test_download_artifact_payload_retries_429_then_succeeds(monkeypatch):
    payload = {"source_event_key": "issue_comment:100"}
    responses = iter(
        [
            FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
        ]
    )
    success_response = FakeGitHubResponse(200, None, "")
    success_response.content = make_zip_payload("deferred-comment.json", payload)

    def fake_request(*args, **kwargs):
        response = next(responses, success_response)
        return response

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sweeper.requests, "request", fake_request)
    monkeypatch.setattr(reviewer_bot, "requests", sweeper.requests)

    status, artifact_payload = sweeper._download_artifact_payload(
        reviewer_bot,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "ok"
    assert artifact_payload == payload


def test_download_artifact_payload_reports_request_exception_unavailable(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sweeper.requests,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            sweeper.requests.RequestException("timeout")
        ),
    )
    monkeypatch.setattr(reviewer_bot, "requests", sweeper.requests)

    status, payload = sweeper._download_artifact_payload(
        reviewer_bot,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None


def test_download_artifact_payload_reports_retry_exhaustion_unavailable(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(sweeper.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        sweeper.requests,
        "request",
        lambda *args, **kwargs: FakeGitHubResponse(429, {"message": "slow down"}, "slow down"),
    )
    monkeypatch.setattr(reviewer_bot, "requests", sweeper.requests)

    status, payload = sweeper._download_artifact_payload(
        reviewer_bot,
        {"archive_download_url": "https://example.com/artifact.zip", "expired": False},
        "deferred-comment.json",
    )

    assert status == "download_unavailable"
    assert payload is None


def test_list_run_artifacts_returns_none_when_api_payload_unavailable(monkeypatch):
    monkeypatch.setattr(sweeper, "_read_api_payload", lambda bot, endpoint: (None, "server_error"))

    assert sweeper._list_run_artifacts(reviewer_bot, 42) is None


@pytest.mark.parametrize(
    ("payload", "workflow_name", "workflow_file", "artifact_name", "payload_name"),
    [
        (
            {"source_event_name": "issue_comment", "source_event_action": "created", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Comment Observer",
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-1-attempt-2",
            "deferred-comment.json",
        ),
        (
            {"source_event_name": "pull_request_review", "source_event_action": "submitted", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Review Submitted Observer",
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-1-attempt-2",
            "deferred-review-submitted.json",
        ),
        (
            {"source_event_name": "pull_request_review", "source_event_action": "dismissed", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Review Dismissed Observer",
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-1-attempt-2",
            "deferred-review-dismissed.json",
        ),
        (
            {"source_event_name": "pull_request_review_comment", "source_event_action": "created", "source_run_id": 1, "source_run_attempt": 2},
            "Reviewer Bot PR Review Comment Observer",
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-1-attempt-2",
            "deferred-review-comment.json",
        ),
    ],
)
def test_deferred_workflow_identity_helpers_match_expected_contract(
    payload,
    workflow_name,
    workflow_file,
    artifact_name,
    payload_name,
):
    assert reviewer_bot.reconcile_module._expected_observer_identity(payload) == (
        workflow_name,
        workflow_file,
    )
    assert reviewer_bot.reconcile_module._artifact_expected_name(payload) == artifact_name
    assert reviewer_bot.reconcile_module._artifact_expected_payload_name(payload) == payload_name


@pytest.mark.parametrize(
    ("workflow_path", "artifact_name", "payload_name"),
    [
        (
            ".github/workflows/reviewer-bot-pr-comment-observer.yml",
            "reviewer-bot-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-comment.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-submitted-observer.yml",
            "reviewer-bot-review-submitted-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-submitted.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml",
            "reviewer-bot-review-dismissed-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-dismissed.json",
        ),
        (
            ".github/workflows/reviewer-bot-pr-review-comment-observer.yml",
            "reviewer-bot-review-comment-context-${{ github.run_id }}-attempt-${{ github.run_attempt }}",
            "deferred-review-comment.json",
        ),
    ],
)
def test_observer_workflow_files_match_expected_artifact_contract(
    workflow_path, artifact_name, payload_name
):
    workflow_text = Path(workflow_path).read_text(encoding="utf-8")

    assert artifact_name in workflow_text
    assert payload_name in workflow_text


def test_validate_workflow_run_artifact_identity_rejects_triggering_name_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Wrong Workflow")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    with pytest.raises(RuntimeError, match="Triggering workflow name mismatch"):
        reviewer_bot.reconcile_module._validate_workflow_run_artifact_identity(payload)


def test_validate_workflow_run_artifact_identity_rejects_run_attempt_mismatch(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_ATTEMPT", "2")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "success")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    with pytest.raises(RuntimeError, match="run_attempt mismatch"):
        reviewer_bot.reconcile_module._validate_workflow_run_artifact_identity(payload)


def test_validate_workflow_run_artifact_identity_requires_successful_conclusion(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_NAME", "Reviewer Bot PR Comment Observer")
    monkeypatch.setenv("WORKFLOW_RUN_TRIGGERING_CONCLUSION", "failure")
    payload = {
        "source_event_name": "issue_comment",
        "source_event_action": "created",
        "source_workflow_name": "Reviewer Bot PR Comment Observer",
        "source_workflow_file": ".github/workflows/reviewer-bot-pr-comment-observer.yml",
        "source_run_id": 1,
        "source_run_attempt": 1,
    }

    with pytest.raises(RuntimeError, match="did not conclude successfully"):
        reviewer_bot.reconcile_module._validate_workflow_run_artifact_identity(payload)


def test_reviewer_board_manifest_includes_projection_repair_attention_option():
    options = reviewer_bot.REVIEWER_BOARD_PROJECT_MANIFEST[
        reviewer_bot.REVIEWER_BOARD_FIELD_NEEDS_ATTENTION
    ]["options"]

    assert reviewer_bot.REVIEWER_BOARD_OPTION_ATTENTION_PROJECTION_REPAIR_REQUIRED in options


def test_classify_event_intent_treats_supported_workflow_run_sources_as_mutating(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING


def test_main_records_repair_needed_when_projection_fails(monkeypatch, tmp_path):
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setenv("EVENT_NAME", "issue_comment")
    monkeypatch.setenv("EVENT_ACTION", "created")
    monkeypatch.setenv("IS_PULL_REQUEST", "false")
    monkeypatch.setenv("ISSUE_NUMBER", "42")
    monkeypatch.setenv("ISSUE_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_USER_TYPE", "User")
    monkeypatch.setenv("COMMENT_AUTHOR", "dana")
    monkeypatch.setenv("COMMENT_ID", "100")
    monkeypatch.setenv("COMMENT_CREATED_AT", "2026-03-17T10:00:00Z")
    monkeypatch.setenv("COMMENT_BODY", "plain text")
    monkeypatch.setattr(reviewer_bot, "acquire_state_issue_lease_lock", lambda: None)
    monkeypatch.setattr(reviewer_bot, "release_state_issue_lease_lock", lambda: True)
    saved_states = []

    def fake_load_state(*, fail_on_unavailable=False):
        return json.loads(json.dumps(state))

    def fake_save_state(updated_state):
        saved_states.append(json.loads(json.dumps(updated_state)))
        state.clear()
        state.update(json.loads(json.dumps(updated_state)))
        return True

    monkeypatch.setattr(reviewer_bot, "load_state", fake_load_state)
    monkeypatch.setattr(reviewer_bot, "save_state", fake_save_state)
    monkeypatch.setattr(reviewer_bot, "process_pass_until_expirations", lambda current_state: (current_state, []))
    monkeypatch.setattr(reviewer_bot, "sync_members_with_queue", lambda current_state: (current_state, []))
    monkeypatch.setattr(reviewer_bot, "get_issue_or_pr_snapshot", lambda issue_number: {"number": issue_number, "state": "open", "labels": [], "pull_request": None})
    monkeypatch.setattr(reviewer_bot, "sync_status_labels_for_items", lambda current_state, issue_numbers: (_ for _ in ()).throw(RuntimeError("projection failed")))
    output_path = tmp_path / "github-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    reviewer_bot.app_module.main(reviewer_bot)
    assert state["active_reviews"]["42"]["repair_needed"]["kind"] == "projection_failure"
    assert len(saved_states) >= 2
