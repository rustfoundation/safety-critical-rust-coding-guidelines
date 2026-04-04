"""Shared retry helpers for reviewer-bot transport and state workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

RETRY_POLICY_NONE = "none"
RETRY_POLICY_IDEMPOTENT_READ = "idempotent_read"


class JitterSource(Protocol):
    def uniform(self, lower: float, upper: float) -> float: ...


@dataclass(frozen=True)
class RetrySpec:
    retry_policy: str
    max_attempts: int
    base_delay_seconds: float
    max_delay_seconds: float = 8.0


def is_retryable_status(status_code: int | None) -> bool:
    return status_code == 429 or (status_code is not None and status_code >= 500)


def additional_attempts_for_policy(retry_policy: str, retry_limit: int) -> int:
    if retry_policy == RETRY_POLICY_NONE:
        return 0
    if retry_policy == RETRY_POLICY_IDEMPOTENT_READ:
        return retry_limit
    raise ValueError(f"Unsupported retry policy: {retry_policy}")


def max_attempts_for_policy(retry_policy: str, retry_limit: int) -> int:
    return 1 + additional_attempts_for_policy(retry_policy, retry_limit)


def bounded_exponential_delay(
    base_delay_seconds: float,
    retry_attempt: int,
    *,
    jitter: JitterSource,
    max_delay_seconds: float = 8.0,
) -> float:
    bounded_base = min(base_delay_seconds * (2 ** max(retry_attempt - 1, 0)), max_delay_seconds)
    return bounded_base + jitter.uniform(0, bounded_base)
