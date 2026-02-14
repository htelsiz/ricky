"""auto_fix — generate fix branches and PRs for issues found in review."""

import logging
import re

from ..clients.github import GitHubClient
from ..config import RickySettings
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)


@tool(
    "auto_fix",
    events=["issue_comment"],
    actions=["created"],
    commands=["@ricky fix"],
)
async def auto_fix(ctx: WebhookContext) -> None:
    """Generate a fix PR when someone says @ricky fix."""
    if ctx.comment is None or ctx.issue is None:
        return

    if not re.search(r"@ricky\s+fix\b", ctx.comment.body, re.IGNORECASE):
        return

    gh = GitHubClient.from_env()
    cfg = RickySettings()  # type: ignore[call-arg]

    owner = ctx.repo.owner
    repo = ctx.repo.name

    if not cfg.auto_fix_enabled:
        await gh.post_issue_comment(
            owner, repo, ctx.issue.number, ctx.installation_id,
            body=(
                "Listen boys, auto-fix is turned off right now. "
                "Set `RICKY_AUTO_FIX_ENABLED=true` if you want me to start fixing shit myself."
            ),
        )
        return

    if not ctx.issue.has_pull_request:
        await gh.post_issue_comment(
            owner, repo, ctx.issue.number, ctx.installation_id,
            body="Boys, I can only fix PRs, not regular issues. Open a PR first.",
        )
        return

    log.info("Auto-fix requested on PR #%d in %s/%s", ctx.issue.number, owner, repo)

    await gh.post_issue_comment(
        owner, repo, ctx.issue.number, ctx.installation_id,
        body="Worst case Ontario, I'll just fix it myself. Give me a minute, boys...",
    )
