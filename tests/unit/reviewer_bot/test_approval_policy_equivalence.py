import json
from pathlib import Path
from types import SimpleNamespace

from scripts.reviewer_bot_core import approval_policy
from scripts.reviewer_bot_lib import review_state, reviews
from scripts.reviewer_bot_lib.config import GitHubApiResult
from tests.fixtures.reviewer_bot import (
    make_state,
    make_tracked_review_state,
    pull_request_payload,
    review_payload,
)

C2C_DELETION_MANIFEST = [
    "compute_pr_approval_state_result",
    "find_triage_approval_after",
]


def _read_table() -> str:
    return Path("tests/fixtures/equivalence/approval_policy/function_classification_table.md").read_text(
        encoding="utf-8"
    )


def _read_scope_fixture() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/approval_policy/in_scope_functions.json").read_text(
            encoding="utf-8"
        )
    )


def test_approval_policy_classification_artifacts_exist():
    assert Path("tests/fixtures/equivalence/approval_policy/function_classification_table.md").exists()
    assert Path("tests/fixtures/equivalence/approval_policy/in_scope_functions.json").exists()


def test_approval_policy_classification_table_freezes_exact_categories_and_scope_boundary():
    table = _read_table()

    for heading in [
        "Stays in `reviews.py`",
        "Moves to `approval_policy.py`",
        "Remains in `reviews_projection.py`",
        "Out of scope",
    ]:
        assert heading in table

    for line in [
        "- `resolve_pr_approval_state`",
        "- `rebuild_pr_approval_state`",
        "- `rebuild_pr_approval_state_result`",
        "- `pr_has_current_write_approval`",
        "- `apply_pr_approval_state`",
        "- `trigger_mandatory_approver_escalation`",
        "- `satisfy_mandatory_approver_requirement`",
        "- `handle_pr_approved_review`",
        "- `compute_pr_approval_state_result`",
        "- `find_triage_approval_after`",
        "- `filter_current_head_reviews_for_cycle`",
        "- `normalize_reviews_with_parsed_timestamps`",
        "- `collect_permission_statuses`",
        "- `compute_pr_approval_state_from_reviews`",
        "- `desired_labels_from_response_state`",
        "- `compute_reviewer_response_state`: out of scope for `C2a/C2b`",
    ]:
        assert line in table


def test_approval_policy_in_scope_fixture_names_exact_functions_for_c2b():
    fixture = _read_scope_fixture()

    assert fixture["harness_id"] == "C2b approval/completion derivation equivalence"
    assert fixture["in_scope_move_functions"] == [
        "compute_pr_approval_state_result",
        "find_triage_approval_after",
    ]
    assert fixture["out_of_scope_functions"] == ["compute_reviewer_response_state"]


def _legacy_compute_pr_approval_state_result(
    bot,
    issue_number: int,
    review_data: dict,
    *,
    pull_request: dict | None = None,
    reviews_data: list[dict] | None = None,
) -> dict[str, object]:
    from scripts.reviewer_bot_lib.reviews_projection import (
        collect_permission_statuses,
        compute_pr_approval_state_from_reviews,
        filter_current_head_reviews_for_cycle,
        normalize_reviews_with_parsed_timestamps,
    )

    boundary = review_state.get_current_cycle_boundary(bot, review_data)
    if boundary is None:
        return reviews._projection_failure("pull_request_unavailable")
    pull_request_result = reviews._pull_request_read_result(bot, issue_number, pull_request)
    if not pull_request_result.get("ok"):
        return pull_request_result
    pull_request = pull_request_result["pull_request"]
    head = pull_request.get("head")
    current_head = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(current_head, str) or not current_head.strip():
        return reviews._projection_failure("pull_request_head_unavailable", "invalid_payload")
    reviews_result = reviews.get_pull_request_reviews_result(bot, issue_number, reviews_data)
    if not reviews_result.get("ok"):
        return reviews_result
    reviews_data = reviews_result["reviews"]

    normalized_reviews = normalize_reviews_with_parsed_timestamps(
        reviews_data,
        parse_timestamp=reviews.parse_github_timestamp,
    )
    survivors = filter_current_head_reviews_for_cycle(
        normalized_reviews,
        boundary=boundary,
        current_head=current_head,
    )
    permission_cache = collect_permission_statuses(
        survivors,
        permission_status=lambda author: reviews._permission_status(bot, author, "push"),
    )
    result = compute_pr_approval_state_from_reviews(
        survivors,
        current_head=current_head,
        permission_statuses=permission_cache,
    )
    if not result.get("ok"):
        return reviews._projection_failure(str(result.get("reason")))
    return result


def _legacy_find_triage_approval_after(bot, reviews_data: list[dict], since):
    permission_cache: dict[str, bool] = {}
    approvals = []
    for review in reviews_data:
        state = str(review.get("state", "")).upper()
        if state != "APPROVED":
            continue
        author = review.get("user", {}).get("login")
        if not isinstance(author, str) or not author:
            continue
        submitted_at = bot.parse_github_timestamp(review.get("submitted_at"))
        if submitted_at is None:
            continue
        if since is not None and submitted_at <= since:
            continue
        approvals.append((submitted_at, str(review.get("id", "")), author))
    approvals.sort(key=lambda item: (item[0], item[1]))
    for submitted_at, _, author in approvals:
        cache_key = author.lower()
        if cache_key not in permission_cache:
            permission_cache[cache_key] = bot.is_triage_or_higher(author)
        if permission_cache[cache_key]:
            return author, submitted_at
    return None


def test_approval_policy_equivalence_matches_legacy_approval_derivation_surface():
    state = make_state()
    review = make_tracked_review_state(
        state,
        42,
        reviewer="alice",
        active_cycle_started_at="2026-03-17T09:00:00Z",
    )
    bot = type(
        "Bot",
        (),
        {
            "github_api_request": staticmethod(
                lambda method, endpoint, data=None, extra_headers=None, **kwargs: GitHubApiResult(
                    200,
                    pull_request_payload(42, head_sha="head-1")
                    if endpoint == "pulls/42"
                    else [
                        review_payload(
                            10,
                            state="APPROVED",
                            submitted_at="2026-03-17T10:01:00Z",
                            commit_id="head-1",
                            author="alice",
                        )
                    ],
                    {},
                    "ok",
                    True,
                    None,
                    0,
                    None,
                )
            ),
            "github_api": staticmethod(lambda method, endpoint, data=None: {}),
            "github": SimpleNamespace(get_user_permission_status=lambda username, permission="push": "granted"),
            "parse_github_timestamp": staticmethod(reviews.parse_github_timestamp),
            "parse_iso8601_timestamp": staticmethod(reviews.parse_github_timestamp),
            "get_user_permission_status": staticmethod(lambda username, required_permission="push": "granted"),
            "is_triage_or_higher": staticmethod(lambda username: username == "alice"),
        },
    )()

    assert approval_policy.compute_pr_approval_state_result(bot, 42, review) == _legacy_compute_pr_approval_state_result(
        bot,
        42,
        review,
    )
    triage_reviews = [
        review_payload(
            11,
            state="APPROVED",
            submitted_at="2026-03-17T10:02:00Z",
            commit_id="head-1",
            author="alice",
        )
    ]
    since = reviews.parse_github_timestamp("2026-03-17T10:00:00Z")
    assert approval_policy.find_triage_approval_after(bot, triage_reviews, since) == _legacy_find_triage_approval_after(
        bot,
        triage_reviews,
        since,
    )


def test_reviews_module_keeps_only_post_f1c_approval_surfaces():
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")

    assert "def compute_pr_approval_state_result(" not in reviews_text
    assert "def find_triage_approval_after(" not in reviews_text
    assert "def rebuild_pr_approval_state_result(" in reviews_text
    assert "def rebuild_pr_approval_state(" in reviews_text


def test_c2c_deletion_manifest_names_in_scope_legacy_derivation_paths_now_reduced_to_delegation():
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")

    assert C2C_DELETION_MANIFEST == [
        "compute_pr_approval_state_result",
        "find_triage_approval_after",
    ]
    assert "def compute_pr_approval_state_result(" not in reviews_text
    assert "def find_triage_approval_after(" not in reviews_text


def test_c2c_caller_migration_moves_production_callers_off_reviews_derivation_path():
    reconcile_text = Path("scripts/reviewer_bot_lib/reconcile.py").read_text(encoding="utf-8")

    assert "find_triage_approval_after," not in reconcile_text
    assert "approval_policy.find_triage_approval_after(" in reconcile_text


def test_c2c_repo_wide_caller_inventory_for_reviews_derivation_path_is_zero_outside_reviews_module():
    root = Path("scripts/reviewer_bot_lib")
    callers = []

    for path in root.glob("*.py"):
        if path.name == "reviews.py":
            continue
        text = path.read_text(encoding="utf-8")
        for symbol in C2C_DELETION_MANIFEST:
            if f"reviews.{symbol}(" in text or f"from .reviews import {symbol}" in text:
                callers.append((path.as_posix(), symbol))

    assert callers == []


def test_f1c_deleted_legacy_derivation_paths_are_no_longer_imported_by_unit_tests():
    projection_text = Path("tests/unit/reviewer_bot/test_reviews_projection.py").read_text(encoding="utf-8")

    assert "reviews.compute_pr_approval_state_result(" not in projection_text
    assert "approval_policy.compute_pr_approval_state_result(" in projection_text
