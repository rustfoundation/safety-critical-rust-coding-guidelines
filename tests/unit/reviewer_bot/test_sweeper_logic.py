from scripts import reviewer_bot
from scripts.reviewer_bot_lib import sweeper
from tests.fixtures.reviewer_bot import make_state


def test_sweeper_creates_keyed_deferred_gaps_for_visible_comments_reviews_and_dismissals(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-25T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 202, "submitted_at": "2026-03-25T11:00:00Z", "state": "APPROVED"},
            {"id": 303, "submitted_at": "2026-03-25T09:00:00Z", "updated_at": "2026-03-25T12:00:00Z", "state": "DISMISSED"},
        ],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "issue_comment:101" in gaps
    assert "pull_request_review:202" in gaps
    assert "pull_request_review_dismissed:303" in gaps
    assert gaps["pull_request_review_dismissed:303"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-dismissed-observer.yml"


def test_sweeper_creates_keyed_deferred_gap_for_visible_review_comments(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-25T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"

    def fake_github_api(method, endpoint, data=None):
        if endpoint == "pulls/42":
            return {"state": "open", "head": {"sha": "head-1"}}
        if endpoint == "issues/42/comments?per_page=100&page=1":
            return []
        if endpoint == "pulls/42/comments?per_page=100":
            return [{"id": 404, "created_at": "2026-03-25T10:30:00Z", "user": {"login": "dana", "type": "User"}}]
        if endpoint.startswith("actions/workflows/"):
            return {"workflow_runs": []}
        return None

    monkeypatch.setattr(reviewer_bot, "github_api", fake_github_api)
    monkeypatch.setattr(reviewer_bot, "get_pull_request_reviews", lambda issue_number: [])

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is True
    gaps = state["active_reviews"]["42"]["deferred_gaps"]
    assert "pull_request_review_comment:404" in gaps
    assert gaps["pull_request_review_comment:404"]["source_workflow_file"] == ".github/workflows/reviewer-bot-pr-review-comment-observer.yml"


def test_sweeper_skips_dismissed_reviews_already_reconciled_by_source_event_key(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-17T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["pull_request_review_dismissed:303"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [
            {"id": 303, "submitted_at": "2026-03-17T09:00:00Z", "updated_at": "2026-03-17T12:00:00Z", "state": "DISMISSED"},
        ],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}


def test_sweeper_skips_events_already_reconciled_by_source_event_key(monkeypatch):
    monkeypatch.setattr(
        sweeper,
        "_now",
        lambda: reviewer_bot.parse_github_timestamp("2026-03-17T12:30:00Z"),
    )
    state = make_state()
    review = reviewer_bot.ensure_review_entry(state, 42, create=True)
    assert review is not None
    review["current_reviewer"] = "alice"
    review["reconciled_source_events"] = ["issue_comment:101", "pull_request_review:202"]
    monkeypatch.setattr(
        reviewer_bot,
        "github_api",
        lambda method, endpoint, data=None: {
            "pulls/42": {"state": "open", "head": {"sha": "head-1"}},
            "issues/42/comments?per_page=100&page=1": [{"id": 101, "created_at": "2026-03-17T10:00:00Z"}],
        }.get(endpoint),
    )
    monkeypatch.setattr(
        reviewer_bot,
        "get_pull_request_reviews",
        lambda issue_number: [{"id": 202, "submitted_at": "2026-03-17T11:00:00Z", "state": "APPROVED"}],
    )

    assert sweeper.sweep_deferred_gaps(reviewer_bot, state) is False
    assert state["active_reviews"]["42"]["deferred_gaps"] == {}
