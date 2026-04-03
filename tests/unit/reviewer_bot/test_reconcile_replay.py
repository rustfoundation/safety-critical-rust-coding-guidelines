from scripts.reviewer_bot_lib import lifecycle, reconcile, review_state
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime
from tests.fixtures.reviewer_bot import make_state


def test_reconcile_active_review_entry_uses_explicit_head_repair_changed_field(monkeypatch):
    state = make_state()
    review = review_state.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.set_config_value("IS_PULL_REQUEST", "true")
    runtime.maybe_record_head_observation_repair = lambda issue_number, review_data: lifecycle.HeadObservationRepairResult(
        changed=False,
        outcome="unchanged",
    )
    runtime.get_pull_request_reviews = lambda issue_number: []
    monkeypatch.setattr(reconcile, "refresh_reviewer_review_from_live_preferred_review", lambda bot, issue_number, review_data, **kwargs: (False, None))
    monkeypatch.setattr(reconcile, "_record_review_rebuild", lambda bot, state_obj, issue_number, review_data: False)

    message, success, changed = reconcile.reconcile_active_review_entry(
        runtime,
        state,
        42,
        require_pull_request_context=True,
    )

    assert success is True
    assert changed is False
    assert "no reconciliation transitions applied" in message
