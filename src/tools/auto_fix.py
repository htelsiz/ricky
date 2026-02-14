"""auto_fix — generate fix branches and PRs for issues found in review.

Triggered by @ricky fix command. Generates fixes via Gemini, creates
a branch, commits the changes, and opens a PR.
"""

from __future__ import annotations

import base64
import logging

from ..clients.github import GitHubClient
from ..config import get_settings
from ..gemini_client import _call_gemini, FALLBACK_SYSTEM_PROMPT
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

_FIX_PROMPT = """\
You are Ricky LaFleur. Someone asked you to fix code issues.

Given the file contents below, apply the fixes described. Return ONLY the
corrected file contents — no explanation, no markdown fences, no commentary.
Just the raw fixed file content."""


@tool(
    "auto_fix",
    events=["issue_comment"],
    actions=["created"],
    commands=["@ricky fix"],
)
async def auto_fix(data: dict) -> None:
    """Generate a fix PR when someone says @ricky fix."""
    import re

    comment = data["comment"]
    body = comment.get("body", "")

    if not re.search(r"@ricky\s+fix\b", body, re.IGNORECASE):
        return

    cfg = get_settings().ricky
    if not cfg.auto_fix_enabled:
        repo = data["repository"]
        installation_id = data["installation"]["id"]
        issue = data["issue"]
        await _gh.post_issue_comment(
            repo["owner"]["login"], repo["name"], issue["number"], installation_id,
            body=(
                "Listen boys, auto-fix is turned off right now. "
                "Set `RICKY_AUTO_FIX_ENABLED=true` if you want me to start fixing shit myself."
            ),
        )
        return

    issue = data["issue"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    issue_number = issue["number"]

    # Only works on PRs (issues with pull_request key)
    if "pull_request" not in issue:
        await _gh.post_issue_comment(
            owner, repo_name, issue_number, installation_id,
            body="Boys, I can only fix PRs, not regular issues. Open a PR first.",
        )
        return

    logger.info("Auto-fix requested on PR #%d in %s/%s", issue_number, owner, repo_name)

    await _gh.post_issue_comment(
        owner, repo_name, issue_number, installation_id,
        body="Worst case Ontario, I'll just fix it myself. Give me a minute, boys...",
    )
