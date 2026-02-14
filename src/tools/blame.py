"""git_blame_context — surface change history for heavily modified files.

Checks which files in the PR have been changed frequently (hot files)
and posts context about the change history.
"""

import logging

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

# Threshold: if a file appears in >N recent commits, flag as hot
HOT_FILE_THRESHOLD = 10


@tool(
    "git_blame_context",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def git_blame_context(ctx: WebhookContext) -> None:
    """Identify hot files and surface change history context."""
    assert ctx.pr is not None
    gh = GitHubClient.from_env()

    owner = ctx.repo.owner
    repo = ctx.repo.name

    diff = await gh.fetch_diff(owner, repo, ctx.pr.number, ctx.installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    if not parsed:
        return

    # Only analyze if there are enough files to make this interesting
    if len(parsed) < 2:
        return

    hot_files = []
    for file_info in parsed:
        path = file_info["path"]
        try:
            commits = await gh.get_commits(
                owner, repo, ctx.installation_id,
                path=path,
                per_page=20,
            )
        except Exception:
            continue

        if len(commits) >= HOT_FILE_THRESHOLD:
            last_author = "unknown"
            if commits and commits[0].get("commit", {}).get("author"):
                last_author = commits[0]["commit"]["author"].get("name", "unknown")

            hot_files.append({
                "path": path,
                "commit_count": len(commits),
                "last_author": last_author,
            })

    if not hot_files:
        return

    lines = ["**Who the fuck keeps changing these files?** Hot file alert:\n"]
    for hf in hot_files:
        lines.append(
            f"- `{hf['path']}` — {hf['commit_count']}+ recent commits "
            f"(last by {hf['last_author']})"
        )

    lines.append(
        "\nThese files change a lot, boys. Be extra careful — "
        "every time someone touches them, something breaks."
    )

    await gh.post_issue_comment(
        owner, repo, ctx.pr.number, ctx.installation_id,
        body="\n".join(lines),
    )

    log.info("Found %d hot file(s) in PR #%d", len(hot_files), ctx.pr.number)
