import json
from pathlib import Path

import pytest

from tests.fixtures import http_responses, reviewer_bot_fakes, reviewer_bot_recorders
from tests.fixtures.focused_fake_services import (
    ArtifactDownloadTransportStub,
    ConfigBag,
    DeferredPayloadStore,
    GitHubStub,
    GraphQLTransportStub,
    HandlerStub,
    LockStub,
    OutputCapture,
    RestTransportStub,
    StateStoreStub,
    TouchTrackerStub,
)
from tests.fixtures.reviewer_bot_fakes import RouteGitHubApi, github_result

pytestmark = pytest.mark.contract


def _load_support_layer_inventory() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/support_layer/symbol_inventory.json").read_text(
            encoding="utf-8"
        )
    )


def test_transport_fake_authority_is_owned_by_reviewer_bot_fakes_module():
    assert reviewer_bot_fakes.RouteGitHubApi is RouteGitHubApi
    assert reviewer_bot_fakes.github_result is github_result


def test_low_level_http_response_helper_has_dedicated_home():
    assert http_responses.FakeGitHubResponse is not None
    assert http_responses.__all__ == ["FakeGitHubResponse"]


def test_reviewer_bot_recorders_module_remains_available_for_shared_recorders():
    assert reviewer_bot_recorders is not None


def test_n2_focused_fake_services_provide_behavioral_authority_for_small_fixture_services(monkeypatch):
    config = ConfigBag(monkeypatch)
    config.set("HELLO", "world")
    output = OutputCapture()
    output.write("changed", "true")
    deferred = DeferredPayloadStore()
    deferred.set_payload({"event": "workflow_run"})
    state_store = StateStoreStub()
    lock = LockStub()
    github = GitHubStub()
    rest = RestTransportStub(github)
    graphql = GraphQLTransportStub()
    artifact = ArtifactDownloadTransportStub()
    handlers = HandlerStub({"handle_comment_event": lambda state: False})
    touch = TouchTrackerStub()
    touch.collect(42)

    assert config.get("HELLO") == "world"
    assert output.writes == [("changed", "true")]
    assert deferred.load() == {"event": "workflow_run"}
    assert state_store.load_state() == {"active_reviews": {}}
    assert lock.calls == []
    assert github._github is None
    assert rest.calls == []
    assert graphql.calls == []
    assert artifact.calls == []
    assert callable(handlers.handle_comment_event)
    assert touch.drain() == [42]


def test_support_layer_contract_focuses_on_active_authority_boundaries_only():
    active_authorities = {
        RouteGitHubApi.__module__,
        github_result.__module__,
        http_responses.FakeGitHubResponse.__module__,
        ConfigBag.__module__,
        reviewer_bot_recorders.__name__,
    }

    assert active_authorities == {
        "tests.fixtures.reviewer_bot_fakes",
        "tests.fixtures.http_responses",
        "tests.fixtures.focused_fake_services",
        "tests.fixtures.reviewer_bot_recorders",
    }


def test_f1a_support_layer_inventory_fixture_records_candidate_classifications_and_importers():
    inventory = _load_support_layer_inventory()

    assert inventory["harness_id"] == "F1a support-layer symbol inventory"
    assert inventory["artifact_classification"] == "active migration proof fixture"
    assert inventory["proof_artifacts"] == [
        {
            "path": "tests/contract/reviewer_bot/test_support_layer_ownership.py",
            "classification": "active migration proof",
        }
    ]
    symbols = {entry["symbol"]: entry for entry in inventory["symbols"]}

    assert symbols["scripts.reviewer_bot_lib.reviews.parse_github_timestamp"]["classification"] == "retained compatibility forwarder"
    assert symbols["scripts.reviewer_bot_lib.review_read_support._projection_failure"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.review_read_support._pull_request_read_result"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.review_read_support.get_pull_request_reviews_result"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.review_read_support._permission_status"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.review_read_support.parse_github_timestamp"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._clear_source_event_key"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._mark_reconciled_source_event"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._update_deferred_gap"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._was_reconciled_source_event"]["classification"] == "retained support owner"
    assert symbols["scripts.reviewer_bot_lib.reviews.build_reviewer_review_record_from_live_review"]["classification"] == "zero-importer deletion candidate"
    assert symbols["scripts.reviewer_bot_lib.reviews.get_preferred_current_reviewer_review_for_cycle"]["classification"] == "zero-importer deletion candidate"
    assert symbols["scripts.reviewer_bot_lib.reviews._compare_records"]["classification"] == "zero-importer deletion candidate"
    assert symbols["scripts.reviewer_bot_lib.reviews.compute_pr_approval_state_result"]["classification"] == "zero-importer deletion candidate"
    assert symbols["scripts.reviewer_bot_lib.reviews.find_triage_approval_after"]["classification"] == "zero-importer deletion candidate"
    assert symbols["scripts.reviewer_bot_lib.reviews.list_open_items_with_status_labels"]["classification"] == "retained support behavior"
    assert symbols["scripts.reviewer_bot_lib.reviews.rebuild_pr_approval_state"]["classification"] == "retained final surface"
    assert symbols["scripts.reviewer_bot_lib.sweeper.sweep_deferred_gaps"]["classification"] == "retained final surface"


def test_f1a_support_layer_inventory_matches_current_active_importer_examples():
    inventory = _load_support_layer_inventory()
    symbols = {entry["symbol"]: entry for entry in inventory["symbols"]}

    assert symbols["scripts.reviewer_bot_lib.reviews.parse_github_timestamp"]["production_importers"] == [
        "scripts/reviewer_bot_lib/runtime.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.review_read_support._projection_failure"]["production_importers"] == [
        "scripts/reviewer_bot_core/approval_policy.py"
    ]
    assert symbols["scripts.reviewer_bot_lib.review_read_support._pull_request_read_result"]["production_importers"] == [
        "scripts/reviewer_bot_core/approval_policy.py",
        "scripts/reviewer_bot_core/review_state_live_repair.py",
        "scripts/reviewer_bot_core/reviewer_response_policy.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.review_read_support.get_pull_request_reviews_result"]["production_importers"] == [
        "scripts/reviewer_bot_core/approval_policy.py",
        "scripts/reviewer_bot_core/reviewer_response_policy.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.review_read_support._permission_status"]["production_importers"] == [
        "scripts/reviewer_bot_core/approval_policy.py"
    ]
    assert symbols["scripts.reviewer_bot_lib.review_read_support.parse_github_timestamp"]["production_importers"] == [
        "scripts/reviewer_bot_core/approval_policy.py",
        "scripts/reviewer_bot_core/review_state_machine.py",
        "scripts/reviewer_bot_core/reviewer_response_policy.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._clear_source_event_key"]["production_importers"] == [
        "scripts/reviewer_bot_lib/reconcile.py",
        "scripts/reviewer_bot_lib/sweeper.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._mark_reconciled_source_event"]["production_importers"] == [
        "scripts/reviewer_bot_lib/reconcile.py",
        "scripts/reviewer_bot_lib/sweeper.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._update_deferred_gap"]["production_importers"] == [
        "scripts/reviewer_bot_lib/reconcile.py",
        "scripts/reviewer_bot_lib/sweeper.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.deferred_gap_bookkeeping._was_reconciled_source_event"]["production_importers"] == [
        "scripts/reviewer_bot_lib/sweeper.py"
    ]
    assert symbols["scripts.reviewer_bot_lib.reviews.list_open_items_with_status_labels"]["production_importers"] == [
        "scripts/reviewer_bot_lib/maintenance.py"
    ]
    assert symbols["scripts.reviewer_bot_lib.reviews.build_reviewer_review_record_from_live_review"]["production_importers"] == []
    assert symbols["scripts.reviewer_bot_lib.reviews.get_preferred_current_reviewer_review_for_cycle"]["production_importers"] == []
    assert symbols["scripts.reviewer_bot_lib.reviews._compare_records"]["production_importers"] == []
    assert symbols["scripts.reviewer_bot_lib.reviews.rebuild_pr_approval_state"]["production_importers"] == [
        "scripts/reviewer_bot_lib/bootstrap_runtime.py",
        "scripts/reviewer_bot_lib/lifecycle.py",
        "scripts/reviewer_bot_lib/runtime.py",
        "scripts/reviewer_bot_lib/sweeper.py",
    ]
    assert symbols["scripts.reviewer_bot_lib.reviews.rebuild_pr_approval_state_result"]["production_importers"] == [
        "scripts/reviewer_bot_lib/reconcile.py"
    ]
    assert symbols["scripts.reviewer_bot_lib.sweeper.sweep_deferred_gaps"]["production_importers"] == [
        "scripts/reviewer_bot_lib/maintenance.py"
    ]


def test_f1b_no_migration_required_production_importers_remain_for_deprecated_support_layer_paths():
    inventory = _load_support_layer_inventory()

    deletion_ready = [
        entry for entry in inventory["symbols"] if entry["classification"] == "zero-importer deletion candidate"
    ]

    assert [entry["symbol"] for entry in deletion_ready] == [
        "scripts.reviewer_bot_lib.reviews.build_reviewer_review_record_from_live_review",
        "scripts.reviewer_bot_lib.reviews.get_preferred_current_reviewer_review_for_cycle",
        "scripts.reviewer_bot_lib.reviews._compare_records",
        "scripts.reviewer_bot_lib.reviews.compute_pr_approval_state_result",
        "scripts.reviewer_bot_lib.reviews.find_triage_approval_after",
    ]
    assert all(entry["production_importers"] == [] for entry in deletion_ready)
    assert all(entry["test_or_fixture_importers"] for entry in deletion_ready)


def test_f1c_deleted_legacy_support_layer_paths_are_explicitly_forbidden():
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")

    assert "def compute_pr_approval_state_result(" not in reviews_text
    assert "def find_triage_approval_after(" not in reviews_text
