from scripts import reviewer_bot


def test_classify_event_intent_cross_repo_review_is_non_mutating_defer(monkeypatch):
    monkeypatch.setenv("PR_IS_CROSS_REPOSITORY", "true")
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_preview_reviewer_board_is_non_mutating(monkeypatch):
    monkeypatch.setenv("MANUAL_ACTION", "preview-reviewer-board")
    intent = reviewer_bot.classify_event_intent("workflow_dispatch", "")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_READONLY


def test_classify_event_intent_same_repo_review_is_non_mutating_defer(monkeypatch):
    intent = reviewer_bot.classify_event_intent("pull_request_review", "submitted")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_same_repo_dismissed_review_is_non_mutating_defer(monkeypatch):
    intent = reviewer_bot.classify_event_intent("pull_request_review", "dismissed")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_review_comment_is_non_mutating_defer(monkeypatch):
    intent = reviewer_bot.classify_event_intent("pull_request_review_comment", "created")
    assert intent == reviewer_bot.EVENT_INTENT_NON_MUTATING_DEFER


def test_classify_event_intent_workflow_run_dismissed_review_is_mutating(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review")
    monkeypatch.setenv("WORKFLOW_RUN_EVENT_ACTION", "dismissed")
    intent = reviewer_bot.classify_event_intent("workflow_run", "completed")
    assert intent == reviewer_bot.EVENT_INTENT_MUTATING


def test_classify_event_intent_treats_supported_workflow_run_sources_as_mutating(monkeypatch):
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "issue_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING
    monkeypatch.setenv("WORKFLOW_RUN_EVENT", "pull_request_review_comment")
    assert reviewer_bot.classify_event_intent("workflow_run", "completed") == reviewer_bot.EVENT_INTENT_MUTATING
