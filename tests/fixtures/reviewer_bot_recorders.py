from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommentSideEffects:
    comments: list[tuple[int, str]]
    reactions: list[tuple[int, str]]


def record_comments(target):
    comments: list[tuple[int, str]] = []
    github_target = getattr(target, "github", target)
    github_target.post_comment = lambda issue_number, body: comments.append((issue_number, body)) or True
    return comments


def record_comment_dicts(target):
    comments = []
    github_target = getattr(target, "github", target)
    github_target.post_comment = lambda issue_number, body: comments.append({"issue_number": issue_number, "body": body}) or True
    return comments


def record_reactions(target):
    reactions: list[tuple[int, str]] = []
    github_target = getattr(target, "github", target)
    github_target.add_reaction = lambda comment_id, reaction: reactions.append((comment_id, reaction)) or True
    return reactions


def record_comment_side_effects(target) -> CommentSideEffects:
    return CommentSideEffects(
        comments=record_comments(target),
        reactions=record_reactions(target),
    )


def record_status_label_ops(target):
    operations = []
    target.add_label_with_status = lambda issue_number, label: operations.append(("add", issue_number, label)) or True
    target.remove_label_with_status = lambda issue_number, label: operations.append(("remove", issue_number, label)) or True
    target.ensure_label_exists = lambda *args, **kwargs: True
    return operations
