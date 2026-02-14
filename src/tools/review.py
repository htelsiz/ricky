"""PR review tool — the core code review functionality."""

import asyncio
import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import build_diff_prompt, parse_diff, valid_lines_for_path
from ..gemini_client import GeminiClient
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

MAX_DIFF_CHARS = 100_000

_MAX_COMMENT_LEN = 200
_MAX_TOTAL_LEN = 4000


def _format_existing_comments(
    pr_comments: list[dict],
    reviews: list[dict],
    issue_comments: list[dict],
) -> str:
    """Format existing PR feedback into a summary for the Gemini prompt."""
    lines: list[str] = []

    for c in pr_comments:
        login = c.get("user", {}).get("login", "unknown")
        tag = login.replace("[bot]", "") if login.endswith("[bot]") else "human"
        path = c.get("path", "")
        line_num = c.get("line") or c.get("original_line") or "?"
        body = (c.get("body") or "")[:_MAX_COMMENT_LEN]
        lines.append(f"[{tag}] {path}:{line_num} — {body}")

    for r in reviews:
        body = (r.get("body") or "").strip()
        if not body:
            continue
        login = r.get("user", {}).get("login", "unknown")
        tag = login.replace("[bot]", "") if login.endswith("[bot]") else "human"
        lines.append(f"[{tag} review] {body[:_MAX_COMMENT_LEN]}")

    for c in issue_comments:
        login = c.get("user", {}).get("login", "unknown")
        tag = login.replace("[bot]", "") if login.endswith("[bot]") else "human"
        body = (c.get("body") or "")[:_MAX_COMMENT_LEN]
        lines.append(f"[{tag} comment] {body}")

    if not lines:
        return ""

    result = "\n".join(lines)
    if len(result) > _MAX_TOTAL_LEN:
        result = result[:_MAX_TOTAL_LEN] + "\n...(truncated)"
    return result


@tool(
    "review",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def review_pr(ctx: WebhookContext) -> None:
    """Fetch the diff, send it to Gemini, post the review."""
    assert ctx.pr is not None
    gh = GitHubClient.from_env()
    gemini = GeminiClient.from_env()

    owner = ctx.repo.owner
    repo = ctx.repo.name
    pr_number = ctx.pr.number

    log.info("Reviewing PR #%d on %s/%s", pr_number, owner, repo)

    diff = await gh.fetch_diff(owner, repo, pr_number, ctx.installation_id)
    if not diff:
        log.warning("Empty diff for PR #%d", pr_number)
        return

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... (diff truncated, boys)"

    parsed_diff = parse_diff(diff)
    if not parsed_diff:
        log.info("No reviewable changes in PR #%d (deletions/binary only)", pr_number)
        return
    structured_diff = build_diff_prompt(parsed_diff)

    styleguide = await gh.fetch_file_raw(
        owner, repo, ".gemini/styleguide.md", ctx.pr.head_ref, ctx.installation_id,
    ) or ""

    # Fetch existing comments in parallel to avoid repeating feedback
    try:
        pr_comments, reviews, issue_comments = await asyncio.gather(
            gh.get_pr_comments(owner, repo, pr_number, ctx.installation_id),
            gh.get_pr_reviews(owner, repo, pr_number, ctx.installation_id),
            gh.get_issue_comments(owner, repo, pr_number, ctx.installation_id),
        )
        existing_feedback = _format_existing_comments(pr_comments, reviews, issue_comments)
    except Exception:
        log.warning("Failed to fetch existing comments, proceeding without", exc_info=True)
        existing_feedback = ""

    review = await gemini.generate_review(
        diff=diff,
        structured_diff=structured_diff,
        pr_title=ctx.pr.title,
        pr_body=ctx.pr.body,
        styleguide=styleguide,
        existing_feedback=existing_feedback,
    )

    summary = review.get("summary", "")
    if not summary and not review.get("comments"):
        log.warning("Empty review generated, skipping")
        return

    commit_sha = ctx.pr.head_sha
    posted = 0

    for c in review.get("comments", []):
        valid_lines = valid_lines_for_path(parsed_diff, c["path"])
        if c["line"] not in valid_lines:
            log.warning("Dropping comment on %s:%d — line not in diff", c["path"], c["line"])
            continue

        try:
            await gh.post_pr_comment(
                owner, repo, pr_number, ctx.installation_id,
                body=c["body"],
                commit_id=commit_sha,
                path=c["path"],
                line=c["line"],
            )
            posted += 1
            ctx.posted_comments.append(f"{c['path']}:{c['line']} — {c['body'][:200]}")
        except Exception:
            log.warning("Failed to post comment on %s:%d", c["path"], c["line"])

    log.info("Posted %d inline comments on PR #%d", posted, pr_number)

    if summary:
        await gh.post_review(
            owner, repo, pr_number, ctx.installation_id,
            commit_id=commit_sha,
            body=summary,
        )
        ctx.posted_comments.append(f"[review summary] {summary[:200]}")


@tool(
    "mention_reply",
    events=["issue_comment"],
    actions=["created"],
)
async def mention_reply(ctx: WebhookContext) -> None:
    """Reply when someone @mentions ricky in a comment."""
    if ctx.comment is None or ctx.issue is None:
        return

    if not re.search(r"@ricky\b", ctx.comment.body, re.IGNORECASE):
        return

    log.info(
        "Replying to @ricky mention in #%d on %s/%s",
        ctx.issue.number, ctx.repo.owner, ctx.repo.name,
    )

    gemini = GeminiClient.from_env()
    reply_body = await gemini.generate_reply(
        question=ctx.comment.body,
        context=f"Issue/PR #{ctx.issue.number}: {ctx.issue.title}",
    )

    if not reply_body:
        return

    gh = GitHubClient.from_env()
    await gh.post_issue_comment(
        ctx.repo.owner, ctx.repo.name, ctx.issue.number, ctx.installation_id,
        body=reply_body,
    )
