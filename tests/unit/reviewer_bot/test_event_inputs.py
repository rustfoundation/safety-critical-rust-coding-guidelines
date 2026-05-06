from scripts.reviewer_bot_lib.event_inputs import (
    build_comment_event_request,
    derive_lifecycle_event_timestamp,
)


class _ConfigBot:
    def __init__(self, values):
        self.values = values

    def get_config_value(self, name, default=""):
        return self.values.get(name, default)


def test_lifecycle_opened_uses_created_at_authority():
    evidence = derive_lifecycle_event_timestamp(
        event_name="issues",
        event_action="opened",
        source_created_at="2026-04-01T00:00:00Z",
        source_updated_at="2026-04-02T00:00:00Z",
        source_closed_at=None,
    )

    assert evidence.selected_timestamp == "2026-04-01T00:00:00+00:00"
    assert evidence.selection_kind == "created_at"
    assert evidence.is_authoritative is True


def test_lifecycle_timestamp_normalizes_timezone_less_values_to_utc():
    evidence = derive_lifecycle_event_timestamp(
        event_name="issues",
        event_action="opened",
        source_created_at="2026-04-01T00:00:00",
        source_updated_at=None,
        source_closed_at=None,
    )

    assert evidence.selected_timestamp == "2026-04-01T00:00:00+00:00"
    assert evidence.selection_kind == "created_at"
    assert evidence.is_authoritative is True


def test_lifecycle_timestamp_normalizes_offset_values_to_canonical_utc():
    evidence = derive_lifecycle_event_timestamp(
        event_name="issues",
        event_action="opened",
        source_created_at="2026-04-01T02:30:00+02:30",
        source_updated_at=None,
        source_closed_at=None,
    )

    assert evidence.selected_timestamp == "2026-04-01T00:00:00+00:00"
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


def test_comment_event_request_normalizes_timezone_less_created_at_to_utc():
    request = build_comment_event_request(
        _ConfigBot(
            {
                "ISSUE_NUMBER": "42",
                "IS_PULL_REQUEST": "true",
                "ISSUE_STATE": "open",
                "ISSUE_AUTHOR": "dana",
                "ISSUE_LABELS": "[]",
                "COMMENT_ID": "210",
                "COMMENT_AUTHOR": "alice",
                "COMMENT_AUTHOR_ID": "7001",
                "COMMENT_BODY": "LGTM",
                "COMMENT_CREATED_AT": "2026-04-01T00:00:00",
                "COMMENT_SOURCE_EVENT_KEY": "issue_comment:210",
                "COMMENT_USER_TYPE": "User",
                "COMMENT_AUTHOR_ASSOCIATION": "MEMBER",
                "COMMENT_SENDER_TYPE": "User",
                "COMMENT_PERFORMED_VIA_GITHUB_APP": "false",
            }
        )
    )

    assert request.comment_created_at == "2026-04-01T00:00:00+00:00"


def test_comment_event_request_normalizes_offset_created_at_to_canonical_utc():
    request = build_comment_event_request(
        _ConfigBot(
            {
                "ISSUE_NUMBER": "42",
                "IS_PULL_REQUEST": "true",
                "ISSUE_STATE": "open",
                "ISSUE_AUTHOR": "dana",
                "ISSUE_LABELS": "[]",
                "COMMENT_ID": "210",
                "COMMENT_AUTHOR": "alice",
                "COMMENT_AUTHOR_ID": "7001",
                "COMMENT_BODY": "LGTM",
                "COMMENT_CREATED_AT": "2026-04-01T02:30:00+02:30",
                "COMMENT_SOURCE_EVENT_KEY": "issue_comment:210",
                "COMMENT_USER_TYPE": "User",
                "COMMENT_AUTHOR_ASSOCIATION": "MEMBER",
                "COMMENT_SENDER_TYPE": "User",
                "COMMENT_PERFORMED_VIA_GITHUB_APP": "false",
            }
        )
    )

    assert request.comment_created_at == "2026-04-01T00:00:00+00:00"
