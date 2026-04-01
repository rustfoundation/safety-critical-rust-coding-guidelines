from scripts import reviewer_bot
from tests.fixtures.reviewer_bot import make_state


def test_load_state_sets_schema_and_epoch_defaults(monkeypatch):
    monkeypatch.setattr(reviewer_bot, "get_state_issue", lambda: {"body": "queue: []\n"})
    state = reviewer_bot.load_state()
    assert state["schema_version"] == reviewer_bot.STATE_SCHEMA_VERSION
    assert state["freshness_runtime_epoch"] == reviewer_bot.FRESHNESS_RUNTIME_EPOCH_LEGACY


def test_get_state_issue_snapshot_uses_retry_aware_read(monkeypatch):
    observed = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["retry_policy"] = kwargs.get("retry_policy")
        return reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"body": "state: ok", "html_url": "https://example.com/state/1"},
            headers={"etag": '"abc"'},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=1,
            transport_error=None,
        )

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)

    snapshot = reviewer_bot.get_state_issue_snapshot()

    assert snapshot is not None
    assert snapshot.etag == '"abc"'
    assert observed["retry_policy"] == "idempotent_read"


def test_conditional_patch_state_issue_sends_if_match_header(monkeypatch):
    observed = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["extra_headers"] = extra_headers
        return reviewer_bot.GitHubApiResult(
            status_code=200,
            payload={"body": data["body"]},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        )

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)

    reviewer_bot.conditional_patch_state_issue("updated", '"etag-1"')

    assert observed["extra_headers"] == {"If-Match": '"etag-1"'}


def test_conditional_patch_state_issue_omits_if_match_when_etag_missing(monkeypatch):
    observed = {}
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["extra_headers"] = extra_headers
        return reviewer_bot.GitHubApiResult(200, {"body": data["body"]}, {}, "ok", True, None, 0, None)

    monkeypatch.setattr(reviewer_bot, "github_api_request", fake_request)

    reviewer_bot.conditional_patch_state_issue("updated", None)

    assert observed["extra_headers"] is None


def test_save_state_retries_precondition_failed_conflict(monkeypatch):
    state = make_state()
    monkeypatch.setattr(reviewer_bot, "STATE_ISSUE_NUMBER", 1)
    snapshot = reviewer_bot.StateIssueSnapshot(
        body="body",
        etag='"etag"',
        html_url="https://example.com/state/1",
    )
    responses = iter(
        [
            reviewer_bot.GitHubApiResult(412, {"message": "precondition failed"}, {}, "precondition failed", False, None, 0, None),
            reviewer_bot.GitHubApiResult(200, {"body": "updated"}, {}, "ok", True, None, 0, None),
        ]
    )
    monkeypatch.setattr(reviewer_bot, "ACTIVE_LEASE_CONTEXT", object())
    monkeypatch.setattr(reviewer_bot, "ensure_state_issue_lease_lock_fresh", lambda: True)
    monkeypatch.setattr(reviewer_bot, "get_state_issue_snapshot", lambda: snapshot)
    monkeypatch.setattr(reviewer_bot, "parse_lock_metadata_from_issue_body", lambda body: {})
    monkeypatch.setattr(
        reviewer_bot,
        "render_state_issue_body",
        lambda state_obj, lock_meta, base_body: "updated",
    )
    monkeypatch.setattr(
        reviewer_bot,
        "conditional_patch_state_issue",
        lambda body, etag=None: next(responses),
    )
    monkeypatch.setattr(reviewer_bot.state_store_module.time, "sleep", lambda *_args, **_kwargs: None)

    assert reviewer_bot.save_state(state) is True
