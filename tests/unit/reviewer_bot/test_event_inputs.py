from scripts.reviewer_bot_lib.event_inputs import derive_lifecycle_event_timestamp


def test_lifecycle_opened_uses_created_at_authority():
    evidence = derive_lifecycle_event_timestamp(
        event_name="issues",
        event_action="opened",
        source_created_at="2026-04-01T00:00:00Z",
        source_updated_at="2026-04-02T00:00:00Z",
        source_closed_at=None,
    )

    assert evidence.selected_timestamp == "2026-04-01T00:00:00Z"
    assert evidence.selection_kind == "created_at"
    assert evidence.is_authoritative is True


def test_lifecycle_unknown_action_does_not_use_updated_at_blanket_fallback():
    evidence = derive_lifecycle_event_timestamp(
        event_name="issues",
        event_action="unknown",
        source_created_at="2026-04-01T00:00:00Z",
        source_updated_at="2026-04-02T00:00:00Z",
        source_closed_at=None,
    )

    assert evidence.is_authoritative is False
    assert evidence.selected_timestamp is None
