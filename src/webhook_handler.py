"""Event routing — PR opened/sync triggers review, @ricky mention triggers reply."""

import logging
import re

from .diff_parser import build_diff_prompt, parse_diff, valid_lines_for_path
from .gemini_client import generate_reply, generate_review
from .github_auth import github_api

logger = logging.getLogger(__name__)

MAX_DIFF_CHARS = 100_000


async def handle_webhook(event: str, data: dict) -> None:
    """Route webhook events to the appropriate handler."""
    action = data.get("action", "")

    if event == "pull_request" and action in ("opened", "synchronize", "reopened"):
        await handle_pull_request(data)
    elif event == "issue_comment" and action == "created":
        await handle_comment(data)


async def handle_pull_request(data: dict) -> None:
    """Fetch the diff, send it to Gemini, post the review."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]

    logger.info("Reviewing PR #%d on %s/%s", pr_number, owner, repo_name)

    # Fetch the diff
    diff_resp = await github_api(
        "GET",
        f"/repos/{owner}/{repo_name}/pulls/{pr_number}",
        installation_id,
        accept="application/vnd.github.diff",
    )
    if diff_resp.status_code != 200:
        logger.error("Failed to fetch diff: %d", diff_resp.status_code)
        return

    diff = diff_resp.text
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n... (diff truncated, boys)"

    # Parse diff for structured line info
    parsed_diff = parse_diff(diff)
    if not parsed_diff:
        logger.info("No reviewable changes in PR #%d (deletions/binary only)", pr_number)
        return
    structured_diff = build_diff_prompt(parsed_diff)

    # Try to fetch the repo's styleguide
    styleguide = await _fetch_styleguide(owner, repo_name, installation_id)

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
            logger.warning(
                "Dropping comment on %s:%d — line not in diff",
                c["path"], c["line"],
            )
            continue

        resp = await github_api(
            "POST",
            f"/repos/{owner}/{repo_name}/pulls/{pr_number}/comments",
            installation_id,
            json={
                "body": c["body"],
                "commit_id": commit_sha,
                "path": c["path"],
                "line": c["line"],
                "side": "RIGHT",
            },
        )
        if resp.status_code in (200, 201):
            posted += 1
        else:
            logger.warning(
                "Failed to post comment on %s:%d: %d %s",
                c["path"], c["line"], resp.status_code, resp.text,
            )

    logger.info("Posted %d inline comments on PR #%d", posted, pr_number)

    # Post summary as a top-level review comment
    if summary:
        resp = await github_api(
            "POST",
            f"/repos/{owner}/{repo_name}/pulls/{pr_number}/reviews",
            installation_id,
            json={"commit_id": commit_sha, "body": summary, "event": "COMMENT"},
        )
        if resp.status_code not in (200, 201):
            logger.error("Failed to post summary review: %d %s", resp.status_code, resp.text)


async def handle_comment(data: dict) -> None:
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

    resp = await github_api(
        "POST",
        f"/repos/{owner}/{repo_name}/issues/{issue_number}/comments",
        installation_id,
        json={"body": reply_body},
    )

    if resp.status_code in (200, 201):
        logger.info("Posted reply on #%d", issue_number)
    else:
        logger.error("Failed to post reply: %d %s", resp.status_code, resp.text)


async def _fetch_styleguide(owner: str, repo: str, installation_id: int) -> str:
    """Try to fetch .gemini/styleguide.md from the repo."""
    resp = await github_api(
        "GET",
        f"/repos/{owner}/{repo}/contents/.gemini/styleguide.md",
        installation_id,
        accept="application/vnd.github.raw+json",
    )
    if resp.status_code == 200:
        return resp.text
    return ""
