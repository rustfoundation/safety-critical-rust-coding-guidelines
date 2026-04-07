import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from scripts.reviewer_bot_core import mandatory_approver_policy
from scripts.reviewer_bot_lib import reviews
from tests.fixtures.reviewer_bot import make_state, make_tracked_review_state


def _load_matrix() -> dict:
    return json.loads(
        Path("tests/fixtures/equivalence/mandatory_approver_policy/decision_matrix.json").read_text(encoding="utf-8")
    )


def _make_bot(*, ensure_label_exists=True, add_label_result=True, post_comment_result=True, remove_label_error=False):
    comments = []
    labels_added = []
    labels_removed = []
    bot = SimpleNamespace(
        github=SimpleNamespace(
            ensure_label_exists=lambda label: ensure_label_exists,
            post_comment=lambda issue_number, body: comments.append((issue_number, body)) or post_comment_result,
        ),
        add_label_with_status=lambda issue_number, label: labels_added.append((issue_number, label)) or add_label_result,
        remove_label_with_status=(
            (lambda issue_number, label: (_ for _ in ()).throw(RuntimeError("remove failed")))
            if remove_label_error
            else (lambda issue_number, label: labels_removed.append((issue_number, label)) or True)
        ),
        logger=SimpleNamespace(event=lambda *args, **kwargs: None),
    )
    return bot, comments, labels_added, labels_removed


def _legacy_trigger_mandatory_approver_escalation(bot, state: dict, issue_number: int) -> bool:
    review_data = reviews.review_state.ensure_review_entry(state, issue_number, create=True)
    if review_data is None:
        return False
    now = reviews._now_iso()
    state_changed = False
    if not review_data.get("mandatory_approver_required"):
        review_data["mandatory_approver_required"] = True
        review_data["mandatory_approver_satisfied_by"] = None
        review_data["mandatory_approver_satisfied_at"] = None
        state_changed = True
    if bot.github.ensure_label_exists(reviews.MANDATORY_TRIAGE_APPROVER_LABEL):
        try:
            if bot.add_label_with_status(issue_number, reviews.MANDATORY_TRIAGE_APPROVER_LABEL):
                if review_data.get("mandatory_approver_label_applied_at") is None:
                    review_data["mandatory_approver_label_applied_at"] = now
                    state_changed = True
        except RuntimeError as exc:
            reviews._log(bot, "warning", f"Unable to apply escalation label on #{issue_number}: {exc}", issue_number=issue_number, error=str(exc))
    if review_data.get("mandatory_approver_pinged_at") is None:
        if bot.github.post_comment(issue_number, reviews.MANDATORY_TRIAGE_ESCALATION_TEMPLATE):
            review_data["mandatory_approver_pinged_at"] = now
            state_changed = True
    return state_changed


def _legacy_satisfy_mandatory_approver_requirement(bot, state: dict, issue_number: int, approver: str) -> bool:
    review_data = reviews.review_state.ensure_review_entry(state, issue_number, create=True)
    if review_data is None or not review_data.get("mandatory_approver_required"):
        return False
    if review_data.get("mandatory_approver_satisfied_at"):
        return False
    now = reviews._now_iso()
    review_data["mandatory_approver_required"] = False
    review_data["mandatory_approver_satisfied_by"] = approver
    review_data["mandatory_approver_satisfied_at"] = now
    try:
        bot.remove_label_with_status(issue_number, reviews.MANDATORY_TRIAGE_APPROVER_LABEL)
    except RuntimeError as exc:
        reviews._log(bot, "warning", f"Unable to remove escalation label on #{issue_number}: {exc}", issue_number=issue_number, error=str(exc))
    bot.github.post_comment(issue_number, reviews.MANDATORY_TRIAGE_SATISFIED_TEMPLATE.format(approver=approver))
    return True


def _build_row(row_id: str):
    state = make_state()
    review = make_tracked_review_state(state, 42, reviewer="alice")
    kwargs = {}
    if row_id == "escalation_required_label_apply_ping_required":
        return state, reviews.trigger_mandatory_approver_escalation, _legacy_trigger_mandatory_approver_escalation, kwargs
    if row_id == "escalation_already_required_label_and_ping_already_recorded":
        review["mandatory_approver_required"] = True
        review["mandatory_approver_label_applied_at"] = "2026-03-20T09:00:00Z"
        review["mandatory_approver_pinged_at"] = "2026-03-20T09:30:00Z"
        return state, reviews.trigger_mandatory_approver_escalation, _legacy_trigger_mandatory_approver_escalation, kwargs
    if row_id == "satisfaction_allowed_with_label_remove":
        review["mandatory_approver_required"] = True
        kwargs = {"approver": "carol"}
        return state, reviews.satisfy_mandatory_approver_requirement, _legacy_satisfy_mandatory_approver_requirement, kwargs
    if row_id == "satisfaction_denied_when_not_required":
        kwargs = {"approver": "carol"}
        return state, reviews.satisfy_mandatory_approver_requirement, _legacy_satisfy_mandatory_approver_requirement, kwargs
    if row_id == "satisfaction_denied_when_already_satisfied":
        review["mandatory_approver_required"] = True
        review["mandatory_approver_satisfied_at"] = "2026-03-20T10:00:00Z"
        kwargs = {"approver": "carol"}
        return state, reviews.satisfy_mandatory_approver_requirement, _legacy_satisfy_mandatory_approver_requirement, kwargs
    raise AssertionError(f"Unhandled row: {row_id}")


def test_h2a_mandatory_approver_matrix_matches_frozen_decision_rows(monkeypatch):
    matrix = _load_matrix()

    assert matrix["harness_id"] == "H2a mandatory-approver decision equivalence"

    monkeypatch.setattr(reviews, "_now_iso", lambda: "2026-03-21T12:00:00+00:00")

    for row in matrix["rows"]:
        state, current_fn, legacy_fn, kwargs = _build_row(row["id"])
        current_state = deepcopy(state)
        legacy_state = deepcopy(state)
        current_bot, current_comments, current_labels_added, current_labels_removed = _make_bot()
        legacy_bot, legacy_comments, legacy_labels_added, legacy_labels_removed = _make_bot()

        current_result = current_fn(current_bot, current_state, 42, **kwargs)
        legacy_result = legacy_fn(legacy_bot, legacy_state, 42, **kwargs)

        assert current_result == row["result"], row["id"]
        assert current_result == legacy_result, row["id"]
        assert current_state == legacy_state, row["id"]
        assert current_comments == legacy_comments, row["id"]
        assert current_labels_added == legacy_labels_added, row["id"]
        assert current_labels_removed == legacy_labels_removed, row["id"]


def test_h2a_mandatory_approver_matrix_fixture_covers_exact_decision_rows():
    matrix = _load_matrix()

    assert [row["id"] for row in matrix["rows"]] == [
        "escalation_required_label_apply_ping_required",
        "escalation_already_required_label_and_ping_already_recorded",
        "satisfaction_allowed_with_label_remove",
        "satisfaction_denied_when_not_required",
        "satisfaction_denied_when_already_satisfied",
    ]


def _legacy_escalation_decision(review_data: dict, *, now: str, label_exists: bool) -> dict[str, object]:
    require_escalation = not review_data.get("mandatory_approver_required")
    return {
        "allow": True,
        "require_escalation": require_escalation,
        "clear_satisfaction": require_escalation,
        "attempt_label_apply": bool(label_exists),
        "record_label_applied_at": bool(label_exists) and review_data.get("mandatory_approver_label_applied_at") is None,
        "post_ping": review_data.get("mandatory_approver_pinged_at") is None,
        "now": now,
    }


def _legacy_satisfaction_decision(review_data: dict, *, approver: str, now: str) -> dict[str, object]:
    if not review_data.get("mandatory_approver_required"):
        return {"allow": False}
    if review_data.get("mandatory_approver_satisfied_at"):
        return {"allow": False}
    return {
        "allow": True,
        "approver": approver,
        "now": now,
        "attempt_label_remove": True,
        "post_comment": True,
    }


def test_h2b_mandatory_approver_policy_matches_legacy_decision_rows():
    matrix = _load_matrix()
    now = "2026-03-21T12:00:00+00:00"

    for row in matrix["rows"]:
        state, _, _, kwargs = _build_row(row["id"])
        review_data = deepcopy(state["active_reviews"]["42"])
        if row["id"].startswith("escalation_"):
            assert mandatory_approver_policy.decide_mandatory_approver_escalation(
                review_data,
                now=now,
                label_exists=True,
            ) == _legacy_escalation_decision(review_data, now=now, label_exists=True)
        else:
            assert mandatory_approver_policy.decide_mandatory_approver_satisfaction(
                review_data,
                approver=str(kwargs["approver"]),
                now=now,
            ) == _legacy_satisfaction_decision(review_data, approver=str(kwargs["approver"]), now=now)


def test_h2b_reviews_module_delegates_mandatory_approver_decisions_to_policy_owner():
    reviews_text = Path("scripts/reviewer_bot_lib/reviews.py").read_text(encoding="utf-8")
    policy_text = Path("scripts/reviewer_bot_core/mandatory_approver_policy.py").read_text(encoding="utf-8")

    assert "mandatory_approver_policy.decide_mandatory_approver_escalation(" in reviews_text
    assert "mandatory_approver_policy.decide_mandatory_approver_satisfaction(" in reviews_text
    assert "def trigger_mandatory_approver_escalation(" in reviews_text
    assert "def satisfy_mandatory_approver_requirement(" in reviews_text
    assert "bot.github.post_comment(" in reviews_text
    assert "bot.add_label_with_status(" in reviews_text
    assert "bot.remove_label_with_status(" in reviews_text
    assert "def decide_mandatory_approver_escalation(" in policy_text
    assert "def decide_mandatory_approver_satisfaction(" in policy_text
    assert "bot.github.post_comment(" not in policy_text
    assert "bot.add_label_with_status(" not in policy_text
    assert "bot.remove_label_with_status(" not in policy_text


def test_h2c_handle_pr_approved_review_has_zero_external_callers():
    callers = []

    for path in Path("scripts").rglob("*.py"):
        if path.as_posix() == "scripts/reviewer_bot_lib/reviews.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "handle_pr_approved_review(" in text or "from .reviews import handle_pr_approved_review" in text:
            callers.append(path.as_posix())

    assert callers == []
