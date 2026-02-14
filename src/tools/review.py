"""PR review tool — the core code review functionality."""

from __future__ import annotations

import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import build_diff_prompt, parse_diff, valid_lines_for_path
from ..gemini_client import generate_reply, generate_review
from ._registry import tool

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 100_000

_gh = GitHubClient()


@tool(
    "review",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def review_pr(data: dict) -> None:
    """Fetch the diff, send it to Gemini, post the review."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]

    logger.info("Reviewing PR #%d on %s/%s", pr_number, owner, repo_name)

    # Fetch the diff
    diff = await _gh.fetch_diff(owner, repo_name, pr_number, installation_id)
    if not diff:
        logger.warning("Empty diff for PR #%d", pr_number)
        return

    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... (diff truncated, boys)"

    # Parse diff for structured line info
    parsed_diff = parse_diff(diff)
    if not parsed_diff:
        logger.info("No reviewable changes in PR #%d (deletions/binary only)", pr_number)
        return
    structured_diff = build_diff_prompt(parsed_diff)

    # Try to fetch the repo's styleguide
    styleguide = await _gh.fetch_file_raw(
        owner, repo_name, ".gemini/styleguide.md", pr["head"]["ref"], installation_id
    )

    # Generate review via Gemini (returns structured dict)
    review = await generate_review(
        diff=diff,
        structured_diff=structured_diff,
        pr_title=pr.get("title", ""),
        pr_body=pr.get("body", "") or "",
        styleguide=styleguide,
    )

    summary = review.get("summary", "")
    if not summary and not review.get("comments"):
        logger.warning("Empty review generated, skipping")
        return

    commit_sha = pr["head"]["sha"]
    posted = 0

    # Post each comment individually on its specific line
    for c in review.get("comments", []):
        valid_lines = valid_lines_for_path(parsed_diff, c["path"])
        if c["line"] not in valid_lines:
            logger.warning("Dropping comment on %s:%d — line not in diff", c["path"], c["line"])
            continue

        ok = await _gh.post_pr_comment(
            owner, repo_name, pr_number, installation_id,
            body=c["body"],
            commit_id=commit_sha,
            path=c["path"],
            line=c["line"],
        )
        if ok:
            posted += 1

    logger.info("Posted %d inline comments on PR #%d", posted, pr_number)

    # Post summary as a top-level review comment
    if summary:
        await _gh.post_review(
            owner, repo_name, pr_number, installation_id,
            commit_id=commit_sha,
            body=summary,
        )


@tool(
    "mention_reply",
    events=["issue_comment"],
    actions=["created"],
)
async def mention_reply(data: dict) -> None:
    """Reply when someone @mentions ricky in a comment."""
    comment = data["comment"]
    body = comment.get("body", "")

    if not re.search(r"@ricky\b", body, re.IGNORECASE):
        return

    repo = data["repository"]
    installation_id = data["installation"]["id"]
    issue = data["issue"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    issue_number = issue["number"]

    logger.info("Replying to @ricky mention in #%d on %s/%s", issue_number, owner, repo_name)

    reply_body = await generate_reply(
        question=body,
        context=f"Issue/PR #{issue_number}: {issue.get('title', '')}",
    )

    if not reply_body:
        return

    ok = await _gh.post_issue_comment(
        owner, repo_name, issue_number, installation_id,
        body=reply_body,
    )
    if ok:
        logger.info("Posted reply on #%d", issue_number)
