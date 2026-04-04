from types import SimpleNamespace

from scripts.reviewer_bot_lib import state_store
from scripts.reviewer_bot_lib.config import (
    FRESHNESS_RUNTIME_EPOCH_LEGACY,
    STATE_SCHEMA_VERSION,
    GitHubApiResult,
    StateIssueSnapshot,
)
from tests.fixtures.fake_clock import FakeClock
from tests.fixtures.fake_jitter import DeterministicJitter
from tests.fixtures.fake_sleeper import RecordingSleeper
from tests.fixtures.recording_logger import RecordingLogger
from tests.fixtures.reviewer_bot import make_state


def test_load_state_sets_schema_and_epoch_defaults():
    bot = SimpleNamespace(get_state_issue=lambda: {"body": "queue: []\n"})

    state = state_store.load_state(bot)

    assert state["schema_version"] == STATE_SCHEMA_VERSION
    assert state["freshness_runtime_epoch"] == FRESHNESS_RUNTIME_EPOCH_LEGACY


def test_get_state_issue_snapshot_uses_retry_aware_read():
    observed = {}

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["retry_policy"] = kwargs.get("retry_policy")
        return GitHubApiResult(
            status_code=200,
            payload={"body": "state: ok", "html_url": "https://example.com/state/1"},
            headers={"etag": '"abc"'},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=1,
            transport_error=None,
        )

    bot = SimpleNamespace(STATE_ISSUE_NUMBER=1, github_api_request=fake_request, get_config_value=lambda name, default="": default)

    snapshot = state_store.get_state_issue_snapshot(bot)

    assert snapshot is not None
    assert snapshot.etag == '"abc"'
    assert observed["retry_policy"] == "idempotent_read"


def test_conditional_patch_state_issue_sends_if_match_header():
    observed = {}

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["extra_headers"] = extra_headers
        return GitHubApiResult(
            status_code=200,
            payload={"body": data["body"]},
            headers={},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=0,
            transport_error=None,
        )

    bot = SimpleNamespace(STATE_ISSUE_NUMBER=1, github_api_request=fake_request)

    state_store.conditional_patch_state_issue(bot, "updated", '"etag-1"')

    assert observed["extra_headers"] == {"If-Match": '"etag-1"'}


def test_conditional_patch_state_issue_omits_if_match_when_etag_missing():
    observed = {}

    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        observed["extra_headers"] = extra_headers
        return GitHubApiResult(200, {"body": data["body"]}, {}, "ok", True, None, 0, None)

    bot = SimpleNamespace(STATE_ISSUE_NUMBER=1, github_api_request=fake_request)

    state_store.conditional_patch_state_issue(bot, "updated", None)

    assert observed["extra_headers"] is None


def test_save_state_retries_precondition_failed_conflict_uses_injected_time_services():
    state = make_state()
    snapshot = StateIssueSnapshot(
        body="body",
        etag='"etag"',
        html_url="https://example.com/state/1",
    )
    responses = iter(
        [
            GitHubApiResult(412, {"message": "precondition failed"}, {}, "precondition failed", False, None, 0, None),
            GitHubApiResult(200, {"body": "updated"}, {}, "ok", True, None, 0, None),
        ]
    )

    clock = FakeClock()
    sleeper = RecordingSleeper()
    jitter = DeterministicJitter(0.25)
    logger = RecordingLogger()

    bot = SimpleNamespace(
        STATE_ISSUE_NUMBER=1,
        ACTIVE_LEASE_CONTEXT=object(),
        clock=clock,
        sleeper=sleeper,
        jitter=jitter,
        logger=logger,
        ensure_state_issue_lease_lock_fresh=lambda: True,
        get_state_issue_snapshot=lambda: snapshot,
        parse_lock_metadata_from_issue_body=lambda body: {},
        render_state_issue_body=lambda state_obj, lock_meta, base_body: "updated",
        conditional_patch_state_issue=lambda body, etag=None: next(responses),
    )

    assert state_store.save_state(bot, state) is True
    assert state["last_updated"] == clock.now().isoformat()
    assert sleeper.calls == [2.25]
    assert jitter.calls == [(0, 2.0)]
    assert logger.records[0]["level"] == "warning"
    assert logger.records[-1]["level"] == "info"


def test_get_state_issue_snapshot_builds_html_url_from_runtime_config_when_missing():
    def fake_request(method, endpoint, data=None, extra_headers=None, **kwargs):
        return GitHubApiResult(
            status_code=200,
            payload={"body": "state: ok"},
            headers={"etag": '"abc"'},
            text="ok",
            ok=True,
            failure_kind=None,
            retry_attempts=1,
            transport_error=None,
        )

    config = {"REPO_OWNER": "rustfoundation", "REPO_NAME": "safety-critical-rust-coding-guidelines"}
    bot = SimpleNamespace(
        STATE_ISSUE_NUMBER=1,
        github_api_request=fake_request,
        get_config_value=lambda name, default="": config.get(name, default),
    )

    snapshot = state_store.get_state_issue_snapshot(bot)

    assert snapshot is not None
    assert snapshot.html_url == "https://github.com/rustfoundation/safety-critical-rust-coding-guidelines/issues/1"
