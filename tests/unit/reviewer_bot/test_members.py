from scripts.reviewer_bot_lib import members, queue
from tests.fixtures.fake_runtime import FakeReviewerBotRuntime


class TextResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


def test_fetch_members_parses_producers_from_members_table(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.rest_transport.stub(
        lambda **kwargs: TextResponse(
            200,
            """
| Member Name | Role | GitHub Username |
| --- | --- | --- |
| Alice Example | Producer | @alice |
| Bob Example | Observer | @bob |
| Carol Example | Producer | carol |
""",
        )
    )

    result = members.fetch_members(runtime)

    assert result.ok is True
    assert result.producers == [
        {"github": "alice", "name": "Alice Example"},
        {"github": "carol", "name": "Carol Example"},
    ]


def test_fetch_members_logs_warning_and_returns_empty_list_on_failure(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.rest_transport.stub(lambda **kwargs: (_ for _ in ()).throw(RuntimeError("timeout")))

    result = members.fetch_members(runtime)

    assert result.ok is False
    assert result.producers == []


def test_queue_sync_members_with_queue_uses_runtime_fetch_members(monkeypatch):
    runtime = FakeReviewerBotRuntime(monkeypatch)
    runtime.stub_fetch_members(lambda: [{"github": "alice", "name": "Alice Example"}])
    state = {"queue": [], "pass_until": [], "current_index": 0}

    updated, changes = queue.sync_members_with_queue(runtime, state)

    assert updated["queue"] == [{"github": "alice", "name": "Alice Example"}]
    assert changes == ["Added alice to queue"]
