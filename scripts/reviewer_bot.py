#!/usr/bin/env python3
"""Bootstrap entrypoint for reviewer-bot."""

import random
import sys
import time

from scripts.reviewer_bot_lib import github_api
from scripts.reviewer_bot_lib.app import build_event_context as build_app_event_context
from scripts.reviewer_bot_lib.app import execute_run as execute_app_run
from scripts.reviewer_bot_lib.app import main as run_app_main
from scripts.reviewer_bot_lib.bootstrap_runtime import (
    build_runtime as build_bootstrap_runtime,
)
from scripts.reviewer_bot_lib.context import EventContext, ExecutionResult
from scripts.reviewer_bot_lib.runtime import ReviewerBotRuntime

ACTIVE_LEASE_CONTEXT = None
TOUCHED_ISSUE_NUMBERS: set[int] = set()
RUNTIME: ReviewerBotRuntime | None = None


def _runtime_bot(runtime: ReviewerBotRuntime | None = None) -> ReviewerBotRuntime:
    if runtime is not None:
        return runtime
    if RUNTIME is None:
        raise RuntimeError("ReviewerBotRuntime not initialized")
    return RUNTIME


def build_event_context(runtime: ReviewerBotRuntime | None = None) -> EventContext:
    return build_app_event_context(_runtime_bot(runtime))


def execute_run(context: EventContext, runtime: ReviewerBotRuntime | None = None) -> ExecutionResult:
    return execute_app_run(_runtime_bot(runtime), context)


def build_runtime() -> ReviewerBotRuntime:
    return _build_runtime()


def main(
    runtime: ReviewerBotRuntime | None = None,
    *,
    runtime_factory=build_runtime,
) -> None:
    resolved_runtime = runtime or RUNTIME or runtime_factory()
    run_app_main(_runtime_bot(resolved_runtime))


def _build_runtime() -> ReviewerBotRuntime:
    return build_bootstrap_runtime(
        requests=github_api.requests,
        sys=sys,
        random=random,
        time=time,
        active_lease_context=ACTIVE_LEASE_CONTEXT,
    )


RUNTIME = _build_runtime()


if __name__ == "__main__":
    main()
