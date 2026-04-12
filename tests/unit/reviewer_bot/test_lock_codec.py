from scripts.reviewer_bot_lib import lock_codec


def test_lock_codec_round_trips_marked_issue_block_metadata():
    lock_meta = {
        "lock_state": "locked",
        "lock_token": "token-123",
        "lock_owner_run_id": "run-1",
    }

    rendered = lock_codec.render_lock_commit_message(lock_meta)
    parsed = lock_codec.parse_lock_commit_message(rendered)

    assert parsed["lock_state"] == "locked"
    assert parsed["lock_token"] == "token-123"
    assert parsed["lock_owner_run_id"] == "run-1"


def test_lock_codec_round_trips_commit_message_metadata():
    lock_meta = {
        "lock_state": "locked",
        "lock_token": "token-123",
        "lock_owner_run_id": "run-1",
    }

    rendered = lock_codec.render_lock_commit_message(lock_meta)
    parsed = lock_codec.parse_lock_commit_message(rendered)

    assert parsed["lock_state"] == "locked"
    assert parsed["lock_token"] == "token-123"
    assert parsed["lock_owner_run_id"] == "run-1"


def test_lock_codec_normalizes_missing_metadata_keys():
    parsed = lock_codec.normalize_lock_metadata({"lock_state": "locked"})

    assert parsed["lock_state"] == "locked"
    assert parsed["lock_token"] is None
    assert parsed["lock_owner_run_id"] is None


def test_lock_codec_rejects_invalid_commit_message():
    import pytest

    with pytest.raises(RuntimeError, match="invalid reviewer-bot lock commit message"):
        lock_codec.parse_lock_commit_message("not a lock commit")
