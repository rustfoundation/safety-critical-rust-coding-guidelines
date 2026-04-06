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
    assert matrix["pending_command_metadata_keys"] == [
        "source_event_key",
        "command_name",
        "issue_number",
        "actor",
        "args",
        "status",
        "created_at",
        "authorization",
        "target",
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

    handoff = privileged_command_policy.validate_accept_no_fls_changes_handoff(
        request,
        ["fls-audit"],
        "granted",
    )
    pending = privileged_command_policy.build_pending_privileged_command(
        source_event_key="issue_comment:100",
        command_name="accept-no-fls-changes",
        issue_number=42,
        actor="alice",
        args=[],
        created_at="2026-04-06T12:34:56+00:00",
        metadata=handoff.metadata or {},
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

    assert handoff.kind == "handoff_allowed"
    assert list(pending.data) == [
        "source_event_key",
        "command_name",
        "issue_number",
        "actor",
        "args",
        "status",
        "created_at",
        "authorization",
        "target",
    ]
    assert plan.plan is not None
    assert plan.plan.ordered_steps == privileged_command_policy.ORDERED_EXECUTION_STEPS
    assert plan.plan.revalidation_checkpoints == privileged_command_policy.REVALIDATION_CHECKPOINTS
    assert plan.plan.commit_message == privileged_command_policy.COMMIT_MESSAGE
    assert plan.plan.pull_request_title == privileged_command_policy.PR_TITLE


def test_c6d_deletion_manifest_proves_automation_no_longer_embeds_removed_planning_logic():
    module_text = Path("scripts/reviewer_bot_lib/automation.py").read_text(encoding="utf-8")

    assert C6D_DELETION_MANIFEST == [
        "embedded PR title/body fallback construction in automation.create_pull_request",
        "embedded branch template derivation at rev-parse call site in handle_accept_no_fls_changes_command",
    ]
    assert "title = title or privileged_command_policy.PR_TITLE" not in module_text
    assert 'f"chore/spec-lock-{branch_date}-issue-{issue_number}"' not in module_text
    assert '["git", "rev-parse", "--verify", planning.plan.branch_name]' in module_text
