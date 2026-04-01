from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state


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
