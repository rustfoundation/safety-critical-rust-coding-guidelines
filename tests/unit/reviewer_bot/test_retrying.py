from scripts.reviewer_bot_lib import retrying
from tests.fixtures.fake_jitter import DeterministicJitter


def test_is_retryable_status_matches_expected_statuses():
    assert retrying.is_retryable_status(429) is True
    assert retrying.is_retryable_status(500) is True
    assert retrying.is_retryable_status(503) is True
    assert retrying.is_retryable_status(404) is False
    assert retrying.is_retryable_status(403) is False
    assert retrying.is_retryable_status(None) is False


def test_additional_attempts_for_policy_supports_known_policies():
    assert retrying.additional_attempts_for_policy(retrying.RETRY_POLICY_NONE, 5) == 0
    assert retrying.additional_attempts_for_policy(retrying.RETRY_POLICY_IDEMPOTENT_READ, 5) == 5


def test_additional_attempts_for_policy_rejects_unknown_policy():
    try:
        retrying.additional_attempts_for_policy("unexpected", 3)
    except ValueError as exc:
        assert "Unsupported retry policy" in str(exc)
    else:
        raise AssertionError("expected ValueError for unsupported retry policy")


def test_max_attempts_for_policy_includes_initial_attempt():
    assert retrying.max_attempts_for_policy(retrying.RETRY_POLICY_NONE, 4) == 1
    assert retrying.max_attempts_for_policy(retrying.RETRY_POLICY_IDEMPOTENT_READ, 4) == 5


def test_bounded_exponential_delay_uses_jitter_and_caps_growth():
    jitter = DeterministicJitter([0.25, 0.5, 0.75])

    assert retrying.bounded_exponential_delay(2.0, 1, jitter=jitter) == 2.25
    assert retrying.bounded_exponential_delay(2.0, 2, jitter=jitter) == 4.5
    assert retrying.bounded_exponential_delay(2.0, 4, jitter=jitter) == 8.75
    assert jitter.calls == [(0, 2.0), (0, 4.0), (0, 8.0)]
