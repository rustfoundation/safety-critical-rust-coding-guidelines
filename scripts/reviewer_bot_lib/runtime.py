"""Explicit runtime service composition for reviewer-bot orchestration."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import (
    AUTHOR_ASSOCIATION_TRUST_ALLOWLIST,
    BOT_MENTION,
    BOT_NAME,
    COMMANDS,
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS,
    DEFERRED_DISCOVERY_OVERLAP_SECONDS,
    EVENT_INTENT_MUTATING,
    EVENT_INTENT_NON_MUTATING_DEFER,
    EVENT_INTENT_NON_MUTATING_READONLY,
    FLS_AUDIT_LABEL,
    LOCK_API_RETRY_LIMIT,
    LOCK_API_RETRY_LIMIT_ENV,
    LOCK_LEASE_TTL_SECONDS,
    LOCK_LEASE_TTL_SECONDS_ENV,
    LOCK_MAX_WAIT_SECONDS,
    LOCK_MAX_WAIT_SECONDS_ENV,
    LOCK_REF_BOOTSTRAP_BRANCH,
    LOCK_REF_BOOTSTRAP_BRANCH_ENV,
    LOCK_REF_NAME,
    LOCK_REF_NAME_ENV,
    LOCK_RENEWAL_WINDOW_SECONDS,
    LOCK_RENEWAL_WINDOW_SECONDS_ENV,
    LOCK_RETRY_BASE_SECONDS,
    LOCK_RETRY_BASE_SECONDS_ENV,
    REVIEW_DEADLINE_DAYS,
    REVIEW_FRESHNESS_RUNBOOK_PATH,
    REVIEW_LABELS,
    REVIEWER_REQUEST_422_TEMPLATE,
    STATE_ISSUE_NUMBER,
    STATE_ISSUE_NUMBER_ENV,
    STATE_READ_RETRY_BASE_SECONDS,
    STATE_READ_RETRY_BASE_SECONDS_ENV,
    STATE_READ_RETRY_LIMIT,
    STATE_READ_RETRY_LIMIT_ENV,
    STATUS_PROJECTION_EPOCH,
    TRANSITION_PERIOD_DAYS,
)


class _EnvConfig:
    def get(self, name: str, default: str = "") -> str:
        return os.environ.get(name, default)

    def set(self, name: str, value: Any) -> None:
        os.environ[name] = str(value)


class _FileOutputSink:
    def __init__(self, config: _EnvConfig):
        self._config = config

    def write(self, name: str, value: str) -> None:
        output_path = self._config.get("GITHUB_OUTPUT", "/dev/null")
        with open(output_path, "a", encoding="utf-8") as output_file:
            output_file.write(f"{name}={value}\n")


class _JsonDeferredPayloadLoader:
    def __init__(self, config: _EnvConfig):
        self._config = config

    def load(self) -> dict:
        path = self._config.get("DEFERRED_CONTEXT_PATH", "").strip()
        if not path:
            raise RuntimeError("Missing DEFERRED_CONTEXT_PATH for workflow_run reconcile")
        with open(Path(path), encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise RuntimeError("Deferred context payload must be a JSON object")
        return payload


class _TouchTracker:
    def __init__(self):
        self._touched: set[int] = set()

    def collect(self, issue_number: int | None) -> None:
        if isinstance(issue_number, int) and issue_number > 0:
            self._touched.add(issue_number)

    def drain(self) -> list[int]:
        touched = sorted(self._touched)
        self._touched.clear()
        return touched


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SystemSleeper:
    def __init__(self, time_module: Any):
        self._time = time_module

    def sleep(self, seconds: float) -> None:
        self._time.sleep(seconds)


class RandomJitterSource:
    def __init__(self, random_module: Any):
        self._random = random_module

    def uniform(self, lower: float, upper: float) -> float:
        return self._random.uniform(lower, upper)


class Uuid4Source:
    def uuid4_hex(self) -> str:
        return uuid.uuid4().hex


class StdErrLogger:
    def __init__(self, sys_module: Any):
        self._sys = sys_module

    def event(self, level: str, message: str, **fields: Any) -> None:
        rendered_fields = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
        suffix = f" {rendered_fields}" if rendered_fields else ""
        self._sys.stderr.write(f"[{level}] {message}{suffix}\n")


class RequestsRestTransport:
    def __init__(self, requests_module: Any):
        self._requests = requests_module

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        return self._requests.request(method, url, headers=headers, json=json_data, timeout=timeout_seconds)


class RequestsGraphQLTransport:
    def __init__(self, requests_module: Any):
        self._requests = requests_module

    def query(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        query: str,
        variables: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        return self._requests.post(
            url,
            headers=headers,
            json={"query": query, "variables": variables or {}},
            timeout=timeout_seconds,
        )


class RequestsArtifactDownloadTransport:
    def __init__(self, requests_module: Any):
        self._requests = requests_module

    def download(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> Any:
        return self._requests.request("GET", url, headers=headers, timeout=timeout_seconds)


class RuntimeInfraServices:
    def __init__(
        self,
        *,
        config: Any,
        outputs: Any,
        deferred_payloads: Any,
        rest_transport: Any,
        graphql_transport: Any,
        artifact_download_transport: Any,
        clock: Any,
        sleeper: Any,
        jitter: Any,
        uuid_source: Any,
        logger: Any,
        touch_tracker: Any,
    ):
        self.config = config
        self.outputs = outputs
        self.deferred_payloads = deferred_payloads
        self.rest_transport = rest_transport
        self.graphql_transport = graphql_transport
        self.artifact_download_transport = artifact_download_transport
        self.clock = clock
        self.sleeper = sleeper
        self.jitter = jitter
        self.uuid_source = uuid_source
        self.logger = logger
        self.touch_tracker = touch_tracker


class RuntimeDomainServices:
    def __init__(self, *, state_store: Any, github: Any, locks: Any, handlers: Any, adapters: Any):
        self.state_store = state_store
        self.github = github
        self.locks = locks
        self.handlers = handlers
        self.adapters = adapters


class ReviewerBotRuntime:
    """Runtime object built from explicit services and named adapters."""

    BOT_NAME = BOT_NAME
    BOT_MENTION = BOT_MENTION
    COMMANDS = COMMANDS
    FLS_AUDIT_LABEL = FLS_AUDIT_LABEL
    AUTHOR_ASSOCIATION_TRUST_ALLOWLIST = AUTHOR_ASSOCIATION_TRUST_ALLOWLIST
    REVIEWER_REQUEST_422_TEMPLATE = REVIEWER_REQUEST_422_TEMPLATE
    REVIEW_FRESHNESS_RUNBOOK_PATH = REVIEW_FRESHNESS_RUNBOOK_PATH
    REVIEW_DEADLINE_DAYS = REVIEW_DEADLINE_DAYS
    TRANSITION_PERIOD_DAYS = TRANSITION_PERIOD_DAYS
    REVIEW_LABELS = REVIEW_LABELS
    DEFERRED_DISCOVERY_OVERLAP_SECONDS = DEFERRED_DISCOVERY_OVERLAP_SECONDS
    DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS = DEFERRED_DISCOVERY_BOOTSTRAP_WINDOW_SECONDS
    EVENT_INTENT_MUTATING = EVENT_INTENT_MUTATING
    EVENT_INTENT_NON_MUTATING_DEFER = EVENT_INTENT_NON_MUTATING_DEFER
    EVENT_INTENT_NON_MUTATING_READONLY = EVENT_INTENT_NON_MUTATING_READONLY
    STATUS_PROJECTION_EPOCH = STATUS_PROJECTION_EPOCH
    datetime = datetime
    timezone = timezone

    def __init__(
        self,
        *,
        requests: Any,
        sys: Any,
        random: Any,
        time: Any,
        config: Any | None = None,
        outputs: Any | None = None,
        deferred_payloads: Any | None = None,
        rest_transport: Any | None = None,
        graphql_transport: Any | None = None,
        artifact_download_transport: Any | None = None,
        clock: Any | None = None,
        sleeper: Any | None = None,
        jitter: Any | None = None,
        uuid_source: Any | None = None,
        logger: Any | None = None,
        state_store: Any,
        github: Any,
        locks: Any,
        handlers: Any,
        adapters: Any,
        touch_tracker: Any | None = None,
        active_lease_context: Any | None = None,
    ):
        self.requests = requests
        self.sys = sys
        self.random = random
        self.time = time
        resolved_config = config or _EnvConfig()
        resolved_touch_tracker = touch_tracker or _TouchTracker()
        self.infra = RuntimeInfraServices(
            config=resolved_config,
            outputs=outputs or _FileOutputSink(resolved_config),
            deferred_payloads=deferred_payloads or _JsonDeferredPayloadLoader(resolved_config),
            rest_transport=rest_transport or RequestsRestTransport(requests),
            graphql_transport=graphql_transport or RequestsGraphQLTransport(requests),
            artifact_download_transport=artifact_download_transport or RequestsArtifactDownloadTransport(requests),
            clock=clock or SystemClock(),
            sleeper=sleeper or SystemSleeper(time),
            jitter=jitter or RandomJitterSource(random),
            uuid_source=uuid_source or Uuid4Source(),
            logger=logger or StdErrLogger(sys),
            touch_tracker=resolved_touch_tracker,
        )
        self.domain = RuntimeDomainServices(
            state_store=state_store,
            github=github,
            locks=locks,
            handlers=handlers,
            adapters=adapters,
        )
        self.config = self.infra.config
        self.outputs = self.infra.outputs
        self.deferred_payloads = self.infra.deferred_payloads
        self.rest_transport = self.infra.rest_transport
        self.graphql_transport = self.infra.graphql_transport
        self.artifact_download_transport = self.infra.artifact_download_transport
        self.clock = self.infra.clock
        self.sleeper = self.infra.sleeper
        self.jitter = self.infra.jitter
        self.uuid_source = self.infra.uuid_source
        self.logger = self.infra.logger
        self.touch_tracker = self.infra.touch_tracker
        self.state_store = self.domain.state_store
        self.github = self.domain.github
        self.locks = self.domain.locks
        self.handlers = self.domain.handlers
        self.adapters = self.domain.adapters
        self.ACTIVE_LEASE_CONTEXT = active_lease_context

    def get_config_value(self, name: str, default: str = "") -> str:
        return self.config.get(name, default)

    def set_config_value(self, name: str, value: Any) -> None:
        self.config.set(name, value)

    def state_issue_number(self) -> int:
        return int(self.get_config_value(STATE_ISSUE_NUMBER_ENV, str(STATE_ISSUE_NUMBER)) or 0)

    def lock_api_retry_limit(self) -> int:
        return int(self.get_config_value(LOCK_API_RETRY_LIMIT_ENV, str(LOCK_API_RETRY_LIMIT)) or 0)

    def lock_retry_base_seconds(self) -> float:
        return float(self.get_config_value(LOCK_RETRY_BASE_SECONDS_ENV, str(LOCK_RETRY_BASE_SECONDS)) or 0.0)

    def lock_max_wait_seconds(self) -> int:
        return int(self.get_config_value(LOCK_MAX_WAIT_SECONDS_ENV, str(LOCK_MAX_WAIT_SECONDS)) or 0)

    def lock_lease_ttl_seconds(self) -> int:
        return int(self.get_config_value(LOCK_LEASE_TTL_SECONDS_ENV, str(LOCK_LEASE_TTL_SECONDS)) or 0)

    def lock_renewal_window_seconds(self) -> int:
        return int(self.get_config_value(LOCK_RENEWAL_WINDOW_SECONDS_ENV, str(LOCK_RENEWAL_WINDOW_SECONDS)) or 0)

    def lock_ref_name(self) -> str:
        return self.get_config_value(LOCK_REF_NAME_ENV, LOCK_REF_NAME)

    def lock_ref_bootstrap_branch(self) -> str:
        return self.get_config_value(LOCK_REF_BOOTSTRAP_BRANCH_ENV, LOCK_REF_BOOTSTRAP_BRANCH)

    def state_read_retry_limit(self) -> int:
        return int(self.get_config_value(STATE_READ_RETRY_LIMIT_ENV, str(STATE_READ_RETRY_LIMIT)) or 0)

    def state_read_retry_base_seconds(self) -> float:
        return float(self.get_config_value(STATE_READ_RETRY_BASE_SECONDS_ENV, str(STATE_READ_RETRY_BASE_SECONDS)) or 0.0)

    def write_output(self, name: str, value: str) -> None:
        self.outputs.write(name, value)

    def load_deferred_payload(self) -> dict:
        return self.deferred_payloads.load()

    def github_api_request(self, *args, **kwargs):
        return self.github.github_api_request(*args, **kwargs)

    def github_api(self, *args, **kwargs):
        return self.github.github_api(*args, **kwargs)

    def collect_touched_item(self, issue_number: int | None) -> None:
        self.touch_tracker.collect(issue_number)

    def drain_touched_items(self) -> list[int]:
        return self.touch_tracker.drain()

    def assert_lock_held(self, context: str) -> None:
        return self.adapters.state_lock.assert_lock_held(context)

    def get_github_token(self) -> str:
        return self.adapters.github.get_github_token()

    def get_github_graphql_token(self, *, prefer_board_token: bool = False) -> str:
        return self.adapters.github.get_github_graphql_token(prefer_board_token=prefer_board_token)

    def github_graphql(self, query: str, variables=None, *, token=None):
        return self.adapters.github.github_graphql(query, variables, token=token)

    # Adapter-only mutable review-state compatibility surface.
    def maybe_record_head_observation_repair(self, issue_number: int, review_data: dict):
        return self.adapters.review.maybe_record_head_observation_repair(issue_number, review_data)

    def get_next_reviewer(self, state: dict, skip_usernames=None):
        return self.adapters.review.get_next_reviewer(state, skip_usernames)

    def strip_code_blocks(self, comment_body: str) -> str:
        return self.adapters.review.strip_code_blocks(comment_body)

    def parse_command(self, comment_body: str):
        return self.adapters.review.parse_command(comment_body)

    def record_assignment(self, state: dict, github: str, issue_number: int, kind: str) -> None:
        return self.adapters.review.record_assignment(state, github, issue_number, kind)

    def reposition_member_as_next(self, state: dict, username: str) -> bool:
        return self.adapters.review.reposition_member_as_next(state, username)

    def parse_iso8601_timestamp(self, value: Any):
        return self.adapters.state_lock.parse_iso8601_timestamp(value)

    def compute_reviewer_response_state(self, issue_number: int, review_data: dict, *, issue_snapshot=None):
        return self.adapters.review.compute_reviewer_response_state(issue_number, review_data, issue_snapshot=issue_snapshot)

    def run_command(self, command, cwd, check=False):
        return self.adapters.automation.run_command(command, cwd, check)

    def summarize_output(self, result, limit: int = 20) -> str:
        return self.adapters.automation.summarize_output(result, limit)

    def list_changed_files(self, repo_root):
        return self.adapters.automation.list_changed_files(repo_root)

    def get_default_branch(self) -> str:
        return self.adapters.automation.get_default_branch()

    def find_open_pr_for_branch_status(self, branch: str):
        return self.adapters.automation.find_open_pr_for_branch_status(branch)

    def create_pull_request(self, branch: str, base: str, issue_number: int):
        return self.adapters.automation.create_pull_request(branch, base, issue_number)

    def parse_issue_labels(self) -> list[str]:
        return self.adapters.automation.parse_issue_labels()

    def normalize_lock_metadata(self, lock_meta: dict | None):
        return self.adapters.state_lock.normalize_lock_metadata(lock_meta)

    def get_state_issue(self):
        return self.adapters.state_lock.get_state_issue()

    def clear_lock_metadata(self):
        return self.adapters.state_lock.clear_lock_metadata()

    def get_state_issue_snapshot(self):
        return self.adapters.state_lock.get_state_issue_snapshot()

    def conditional_patch_state_issue(self, body: str, etag: str | None = None):
        return self.adapters.state_lock.conditional_patch_state_issue(body, etag)

    def parse_lock_metadata_from_issue_body(self, body: str):
        return self.adapters.state_lock.parse_lock_metadata_from_issue_body(body)

    def render_state_issue_body(self, state: dict, lock_meta: dict, base_body: str | None = None, *, preserve_state_block: bool = False):
        return self.adapters.state_lock.render_state_issue_body(
            state,
            lock_meta,
            base_body,
            preserve_state_block=preserve_state_block,
        )

    def get_state_issue_html_url(self):
        return self.adapters.state_lock.get_state_issue_html_url()

    def get_lock_ref_display(self):
        return self.adapters.state_lock.get_lock_ref_display()

    def get_lock_ref_snapshot(self):
        return self.adapters.state_lock.get_lock_ref_snapshot()

    def build_lock_metadata(self, *args, **kwargs):
        return self.adapters.state_lock.build_lock_metadata(*args, **kwargs)

    def create_lock_commit(self, parent_sha: str, tree_sha: str, lock_meta: dict):
        return self.adapters.state_lock.create_lock_commit(parent_sha, tree_sha, lock_meta)

    def cas_update_lock_ref(self, new_sha: str):
        return self.adapters.state_lock.cas_update_lock_ref(new_sha)

    def lock_is_currently_valid(self, lock_meta: dict, now: datetime | None = None):
        return self.adapters.state_lock.lock_is_currently_valid(lock_meta, now)

    def renew_state_issue_lease_lock(self, context):
        result = self.adapters.state_lock.renew_state_issue_lease_lock(context)
        self.ACTIVE_LEASE_CONTEXT = self.adapters.state_lock.get_active_lease_context()
        return result

    def ensure_state_issue_lease_lock_fresh(self) -> bool:
        return self.adapters.state_lock.ensure_state_issue_lease_lock_fresh()

    def acquire_state_issue_lease_lock(self):
        context = self.adapters.state_lock.acquire_state_issue_lease_lock()
        self.ACTIVE_LEASE_CONTEXT = self.adapters.state_lock.get_active_lease_context()
        return context

    def release_state_issue_lease_lock(self) -> bool:
        result = self.adapters.state_lock.release_state_issue_lease_lock()
        self.ACTIVE_LEASE_CONTEXT = self.adapters.state_lock.get_active_lease_context()
        return result

    def fetch_members(self):
        from . import members as members_module

        return members_module.fetch_members(self)
