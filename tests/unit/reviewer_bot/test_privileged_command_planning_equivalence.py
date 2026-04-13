import json
from pathlib import Path

from scripts.reviewer_bot_core import privileged_command_policy
from tests.fixtures.comment_routing_harness import CommentRoutingHarness

C6D_DELETION_MANIFEST = [
    "embedded PR title/body fallback construction in automation.create_pull_request",
    "embedded branch template derivation at rev-parse call site in handle_accept_no_fls_changes_command",
]


def _load_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/privileged_command_planning/contract_matrix.json").read_text(
            encoding="utf-8"
        )
    )


def test_privileged_command_planning_contract_matrix_exists_and_lists_ordered_plan_outputs():
    matrix = _load_matrix()

    assert matrix["harness_id"] == "C6a privileged command planning contract matrix"
    assert matrix["ordered_execution_steps"] == [
        "working_tree_clean_check",
        "audit_no_impact_check",
        "spec_lock_update",
        "changed_files_validation",
        "branch_name_derivation",
        "branch_existence_check",
        "branch_creation",
        "git_add_spec_lock",
        "git_commit",
        "git_push",
        "pull_request_create",
    ]


def test_privileged_command_planning_contract_matrix_freezes_messages_revalidation_and_handoff_metadata():
    matrix = _load_matrix()

    assert matrix["commit_message"] == "chore: update spec.lock; no affected guidelines"
    assert matrix["pull_request_title"] == "chore: update spec.lock (no guideline impact)"
    assert matrix["branch_name_format"] == "chore/spec-lock-<YYYY-MM-DD>-issue-<issue_number>"
    assert matrix["revalidation_checkpoints"] == [
        "issue_not_pull_request",
        "fls_audit_label_present",
        "triage_permission_granted",
        "working_tree_clean_before_update",
        "audit_no_impact_before_update",
        "changed_files_exact_after_update",
    ]
    assert matrix["handoff_fail_closed_reasons"] == [
        "pull_request_target_not_allowed",
        "missing_fls_audit_label",
        "authorization_unavailable",
        "authorization_failed",
    ]
    assert matrix["revalidation_fail_closed_reasons"] == [
        "unsupported_command",
        "pull_request_target_not_allowed",
        "missing_fls_audit_label",
        "authorization_unavailable",
        "authorization_failed",
    ]
    assert matrix["execution_result_codes"] == [
        "working_tree_not_clean",
        "audit_reported_guideline_impact",
        "audit_failed",
        "update_failed",
        "already_up_to_date",
        "unexpected_changed_files",
        "branch_or_push_failed",
        "pull_request_creation_failed",
        "opened_pull_request",
    ]
    assert matrix["pending_command_metadata_keys"] == [
        "source_event_key",
        "command_name",
        "issue_number",
        "actor",
        "authorization_required_permission",
        "authorization_authorized",
        "target_kind",
        "target_number",
        "target_labels_snapshot",
        "status",
        "created_at",
        "completed_at",
        "result_code",
        "result_message",
        "opened_pr_url",
    ]
    assert matrix["execute_plan_keys"] == ["record", "execution_context"]
    assert matrix["execute_plan_record_keys"] == matrix["pending_command_metadata_keys"]
    assert matrix["execute_plan_execution_context_keys"] == [
        "target_repo_root",
        "base_branch",
        "branch_probe_name",
        "branch_name",
        "expected_changed_files",
        "existing_open_pr_url",
    ]
    assert matrix["trusted_acknowledgment_comment"].startswith("✅ Recorded pending privileged command")


def test_privileged_command_policy_produces_frozen_handoff_metadata_and_ordered_plan(monkeypatch):
    harness = CommentRoutingHarness(monkeypatch)
    request = harness.request(
        issue_number=42,
        is_pull_request=False,
        comment_author="alice",
        comment_body="@guidelines-bot /accept-no-fls-changes",
    )

    request = request.__class__(**{**request.__dict__, "issue_labels": ("fls-audit",)})
    handoff = privileged_command_policy.validate_accept_no_fls_changes_handoff(
        request,
        "granted",
        source_event_key="issue_comment:100",
    )
    pending = privileged_command_policy.build_pending_privileged_command(
        created_at="2026-04-06T12:34:56+00:00",
        handoff=handoff,
    )
    plan = privileged_command_policy.plan_accept_no_fls_changes_execution(
        issue_number=42,
        audit_returncode=0,
        audit_details="",
        update_returncode=0,
        update_details="",
        changed_files_after=["src/spec.lock"],
        branch_date="2026-04-06",
        base_branch="main",
        branch_exists=False,
    )

    assert isinstance(handoff, privileged_command_policy.AllowedPrivilegedHandoff)
    assert list(pending.__dict__) == [
        "source_event_key",
        "command_name",
        "issue_number",
        "actor",
        "authorization_required_permission",
        "authorization_authorized",
        "target_kind",
        "target_number",
        "target_labels_snapshot",
        "status",
        "created_at",
        "completed_at",
        "result_code",
        "result_message",
        "opened_pr_url",
    ]
    assert plan.ordered_steps == privileged_command_policy.ORDERED_EXECUTION_STEPS
    assert plan.revalidation_checkpoints == privileged_command_policy.REVALIDATION_CHECKPOINTS
    assert plan.expected_changed_files == ["src/spec.lock"]
    assert plan.branch_probe_name == "chore/spec-lock-2026-04-06-issue-42"
    assert plan.commit_message == privileged_command_policy.COMMIT_MESSAGE
    assert plan.pull_request_title == privileged_command_policy.PR_TITLE
    assert plan.git_checkout_args == ["git", "checkout", "-b", "chore/spec-lock-2026-04-06-issue-42"]
    assert plan.git_push_args == ["git", "push", "origin", "chore/spec-lock-2026-04-06-issue-42"]


def test_privileged_command_policy_prevalidation_and_revalidation_return_typed_execution_handoff():
    preflight = privileged_command_policy.prevalidate_accept_no_fls_changes_request(
        type(
            "Request",
            (),
            {
                "is_pull_request": False,
                "issue_labels": ("fls-audit",),
                "issue_number": 42,
                "actor": "alice",
            },
        )(),
        "granted",
        [],
    )
    revalidation = privileged_command_policy.revalidate_pending_accept_no_fls_changes(
        privileged_command_policy.PendingAcceptNoFlsChangesRecord(
            source_event_key="issue_comment:100",
            command_name=privileged_command_policy.PrivilegedCommandId.ACCEPT_NO_FLS_CHANGES.value,
            issue_number=42,
            actor="alice",
            authorization_required_permission="triage",
            authorization_authorized=True,
            target_kind="issue",
            target_number=42,
            target_labels_snapshot=("fls-audit",),
            status="pending",
            created_at="2026-04-06T12:34:56+00:00",
        ),
        {"number": 42, "labels": [{"name": "fls-audit"}]},
        "granted",
        target_repo_root="/tmp/repo",
    )

    assert isinstance(preflight, privileged_command_policy.ExecutePrivilegedPlan)
    assert list(preflight.__dict__) == ["record", "execution_context"]
    assert preflight.record.command_name == "accept-no-fls-changes"
    assert preflight.record.target_labels_snapshot == ("fls-audit",)
    assert preflight.execution_context.target_repo_root == ""
    assert isinstance(revalidation, privileged_command_policy.ExecutePrivilegedPlan)
    assert revalidation.record.command_name == "accept-no-fls-changes"
    assert revalidation.record.target_labels_snapshot == ("fls-audit",)
    assert revalidation.execution_context.target_repo_root == "/tmp/repo"


def test_j1_privileged_policy_derives_branch_probe_and_final_plan_names_explicitly():
    assert privileged_command_policy.derive_accept_no_fls_changes_branch_name(
        issue_number=42,
        branch_date="2026-04-06",
    ) == "chore/spec-lock-2026-04-06-issue-42"
    assert privileged_command_policy.derive_accept_no_fls_changes_branch_name(
        issue_number=42,
        branch_date="2026-04-06",
        branch_suffix="123456",
    ) == "chore/spec-lock-2026-04-06-issue-42-123456"


def test_j1_privileged_policy_separates_post_update_assessment_from_final_plan_construction():
    assessment = privileged_command_policy.assess_accept_no_fls_changes_post_update(
        audit_returncode=0,
        audit_details="",
        update_returncode=0,
        update_details="",
        changed_files_after=["src/spec.lock"],
    )

    assert assessment is None


def test_c6d_deletion_manifest_proves_automation_no_longer_embeds_removed_planning_logic():
    module_text = Path("scripts/reviewer_bot_lib/automation.py").read_text(encoding="utf-8")

    assert C6D_DELETION_MANIFEST == [
        "embedded PR title/body fallback construction in automation.create_pull_request",
        "embedded branch template derivation at rev-parse call site in handle_accept_no_fls_changes_command",
    ]
    assert "title = title or privileged_command_policy.PR_TITLE" not in module_text
    assert 'f"chore/spec-lock-{branch_date}-issue-{issue_number}"' not in module_text
    assert "def _resolve_accept_no_fls_changes_plan(" in module_text
    assert '["git", "rev-parse", "--verify", provisional.branch_probe_name]' in module_text
