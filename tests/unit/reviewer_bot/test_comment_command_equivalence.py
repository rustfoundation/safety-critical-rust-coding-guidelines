import json
from pathlib import Path

from scripts.reviewer_bot_core import comment_command_policy
from scripts.reviewer_bot_lib import commands, comment_application
from scripts.reviewer_bot_lib import config as config_module
from tests.fixtures.commands_harness import CommandHarness
from tests.fixtures.reviewer_bot import make_state
from tests.fixtures.reviewer_bot_recorders import record_comment_side_effects

C3B2_DELETION_MANIFEST = [
    "pass",
    "away",
    "label",
    "sync-members",
    "queue",
    "commands",
    "claim",
    "release",
    "rectify",
    "r?-user",
    "assign-from-queue",
    "r?",
    "_multiple_commands",
    "_malformed_known",
    "_malformed_unknown",
    "unknown_command",
]


def _load_fixture() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/comment_command/decision_scope.json").read_text(
            encoding="utf-8"
        )
    )


def _legacy_decide_comment_command(bot, request, classified, *, actor_class: str, commands_help: str) -> dict:
    decision = comment_command_policy.decide_comment_command(
        bot,
        request,
        classified,
        actor_class=actor_class,
        commands_help=commands_help,
    )
    if isinstance(decision, dict):
        return decision
    return {
        "kind": decision.kind,
        "handler": decision.handler_name,
        "handler_args": decision.handler_args,
        "needs_assignment_request": decision.needs_assignment_request,
        "result_shape": decision.result_shape,
        "state_changed_from": decision.state_changed_from,
        "response": decision.response,
        "success": decision.success,
        "react": decision.react,
    }


def _legacy_apply_ordinary_decision(bot, state: dict, request, decision: dict) -> bool:
    issue_number = request.issue_number
    review_data = comment_application.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    assignment_request = comment_application.build_assignment_request_from_comment(request)
    if decision["kind"] == "handler_call":
        handler = getattr(commands, decision["handler"])
        handler_args = [bot, state, *decision["handler_args"]]
        handler_kwargs = {}
        if decision["needs_assignment_request"]:
            handler_kwargs["request"] = assignment_request
        result = handler(*handler_args, **handler_kwargs)
        if decision["result_shape"] == "pair":
            response, success = result
            state_changed = success if decision.get("state_changed_from") == "success" else False
        else:
            response, success, state_changed = result
    else:
        response = decision["response"]
        success = decision["success"]
        state_changed = bool(decision.get("state_changed", False))

    if request.comment_id > 0 and decision.get("react", True):
        bot.github.add_reaction(request.comment_id, "eyes")
        if success:
            bot.github.add_reaction(request.comment_id, "+1")
    if response:
        bot.github.post_comment(issue_number, response)
    return state_changed


def _normalize_decision(decision):
    if isinstance(decision, dict):
        return decision
    return {
        "kind": decision.kind,
        "handler": decision.handler_name,
        "handler_args": decision.handler_args,
        "needs_assignment_request": decision.needs_assignment_request,
        "result_shape": decision.result_shape,
        "state_changed_from": decision.state_changed_from,
        "response": decision.response,
        "success": decision.success,
        "react": decision.react,
    }


def _stub_common_handlers(monkeypatch):
    monkeypatch.setattr(commands, "handle_queue_command", lambda bot, state: ("queue snapshot", True))
    monkeypatch.setattr(commands, "handle_label_command", lambda bot, state, issue_number, labels, request=None: ("label updated", True, True))


def test_comment_command_fixture_declares_ordinary_scope_and_deferred_privileged_path():
    fixture = _load_fixture()

    assert fixture["harness_id"] == "C3b1 command decision equivalence"
    assert fixture["deferred_command_set"] == ["accept-no-fls-changes"]
    assert fixture["equivalence_scenarios"] == [
        "queue_success",
        "label_triplet_handler",
        "away_missing_date",
        "multiple_commands_warning",
        "unknown_command_error",
    ]


def test_command_policy_explicitly_defers_privileged_handoff_path(monkeypatch):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_comment_request(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /accept-no-fls-changes",
        issue_author="dana",
        is_pull_request=False,
    )

    decision = comment_command_policy.decide_comment_command(
        harness.runtime,
        request,
        {"command": "accept-no-fls-changes", "args": [], "command_count": 1},
        actor_class="repo_user_principal",
        commands_help="help text",
    )

    assert decision == {"kind": "deferred_privileged_handoff"}


def test_i1_comment_policy_types_ordinary_command_output_shape(monkeypatch):
    harness = CommandHarness(monkeypatch)
    request = harness.typed_comment_request(
        issue_number=42,
        actor="alice",
        body="@guidelines-bot /queue",
        issue_author="dana",
        is_pull_request=False,
    )

    decision = comment_command_policy.decide_comment_command(
        harness.runtime,
        request,
        {"command": "queue", "args": [], "command_count": 1},
        actor_class="repo_user_principal",
        commands_help="help text",
    )

    assert isinstance(decision, comment_command_policy.OrdinaryCommentUseCaseResult)
    assert list(decision.__dataclass_fields__) == [
        "kind",
        "handler_name",
        "handler_args",
        "needs_assignment_request",
        "result_shape",
        "state_changed_from",
        "response",
        "success",
        "react",
    ]


def test_i2_comment_application_routing_does_not_reopen_command_semantics_in_adapter():
    module_text = Path("scripts/reviewer_bot_lib/comment_application.py").read_text(encoding="utf-8")

    assert 'if routing.kind in {"freshness_only", "both"}:' in module_text
    assert 'if routing.kind in {"command_only", "both"}:' in module_text
    assert "if command == " not in module_text


def test_c3b2_deletion_manifest_keeps_privileged_handoff_outside_ordinary_scope():
    fixture = _load_fixture()

    assert fixture["in_scope_command_set"] == C3B2_DELETION_MANIFEST
    assert fixture["deferred_command_set"] == ["accept-no-fls-changes"]


def test_command_decision_equivalence_matches_legacy_for_ordinary_paths(monkeypatch):
    fixture = _load_fixture()

    scenarios = [
        (
            "queue_success",
            {"command": "queue", "args": [], "command_count": 1},
            CommandHarness(monkeypatch).typed_comment_request(
                issue_number=42,
                actor="alice",
                body="@guidelines-bot /queue",
                issue_author="dana",
                is_pull_request=False,
            ),
        ),
        (
            "label_triplet_handler",
            {"command": "label", "args": ["+triage"], "command_count": 1},
            CommandHarness(monkeypatch).typed_comment_request(
                issue_number=42,
                actor="alice",
                body="@guidelines-bot /label +triage",
                issue_author="dana",
                is_pull_request=False,
            ),
        ),
        (
            "away_missing_date",
            {"command": "away", "args": [], "command_count": 1},
            CommandHarness(monkeypatch).typed_comment_request(
                issue_number=42,
                actor="alice",
                body="@guidelines-bot /away",
                issue_author="dana",
                is_pull_request=False,
            ),
        ),
        (
            "multiple_commands_warning",
            {"command": "_multiple_commands", "args": [], "command_count": 2},
            CommandHarness(monkeypatch).typed_comment_request(
                issue_number=42,
                actor="alice",
                body="@guidelines-bot /queue\n@guidelines-bot /pass",
                issue_author="dana",
                is_pull_request=False,
            ),
        ),
        (
            "unknown_command_error",
            {"command": "does-not-exist", "args": [], "command_count": 1},
            CommandHarness(monkeypatch).typed_comment_request(
                issue_number=42,
                actor="alice",
                body="@guidelines-bot /does-not-exist",
                issue_author="dana",
                is_pull_request=False,
            ),
        ),
    ]

    assert fixture["equivalence_scenarios"] == [scenario[0] for scenario in scenarios]

    for scenario_name, classified, request in scenarios:
        _stub_common_handlers(monkeypatch)
        old_harness = CommandHarness(monkeypatch)
        new_harness = CommandHarness(monkeypatch)
        old_state = make_state()
        new_state = make_state()
        old_effects = record_comment_side_effects(old_harness.runtime)
        old_decision = _legacy_decide_comment_command(
            old_harness.runtime,
            request,
            classified,
            actor_class="repo_user_principal",
            commands_help=config_module.get_commands_help(),
        )
        old_changed = _legacy_apply_ordinary_decision(old_harness.runtime, old_state, request, old_decision)
        old_reactions = list(old_effects.reactions)
        old_comments = list(old_effects.comments)

        new_effects = record_comment_side_effects(new_harness.runtime)
        new_decision = comment_command_policy.decide_comment_command(
            new_harness.runtime,
            request,
            classified,
            actor_class="repo_user_principal",
            commands_help=config_module.get_commands_help(),
        )
        new_changed = comment_application.apply_comment_command(
            new_harness.runtime,
            new_state,
            request,
            dict(classified),
            classify_issue_comment_actor=lambda current_request: "repo_user_principal",
        )

        assert _normalize_decision(new_decision) == _normalize_decision(old_decision), scenario_name
        assert new_changed == old_changed, scenario_name
        assert new_state == old_state, scenario_name
        assert new_effects.comments == old_comments, scenario_name
        assert new_effects.reactions == old_reactions, scenario_name
        assert new_harness.runtime.drain_touched_items() == old_harness.runtime.drain_touched_items(), scenario_name
