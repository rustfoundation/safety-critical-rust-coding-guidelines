from types import SimpleNamespace

from scripts.reviewer_bot_core.comment_routing_policy import (
    PrCommentRouterOutcome,
    classify_pr_comment_router_outcome,
)
from scripts.reviewer_bot_lib.context import PrCommentAdmission


def test_ambiguous_cross_repo_pr_comment_fails_to_deferred_lane():
    request = SimpleNamespace(
        is_pull_request=True,
        comment_user_type="User",
        comment_author="reviewer",
        comment_sender_type="User",
        comment_installation_id=None,
        comment_performed_via_github_app=False,
        comment_author_association="MEMBER",
    )
    admission = PrCommentAdmission(
        route_outcome=PrCommentRouterOutcome.TRUSTED_DIRECT,
        declared_trust_class="pr_trusted_direct",
        github_repository="rustfoundation/safety-critical-rust-coding-guidelines",
        pr_head_full_name="fork/repo",
        pr_author="contributor",
        issue_state="open",
        issue_labels=(),
        comment_author_id=1,
        github_run_id=1,
        github_run_attempt=1,
    )

    assert classify_pr_comment_router_outcome(request, admission, is_self_comment=False) == PrCommentRouterOutcome.DEFERRED_RECONCILE
