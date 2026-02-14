"""size_guard — PR size enforcement via GitHub Checks API."""

import logging

from ..clients.github import GitHubClient
from ..config import RickySettings
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)


@tool(
    "size_guard",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def size_guard(ctx: WebhookContext) -> None:
    """Check PR size and post a GitHub Check Run."""
    assert ctx.pr is not None
    gh = GitHubClient.from_env()
    cfg = RickySettings()  # type: ignore[call-arg]

    owner = ctx.repo.owner
    repo = ctx.repo.name

    diff = await gh.fetch_diff(owner, repo, ctx.pr.number, ctx.installation_id)
    if not diff:
        return

    lines_added = 0
    lines_removed = 0
    files_changed: set[str] = set()

    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            parts = line.split(" b/")
            if len(parts) > 1:
                files_changed.add(parts[-1])
        elif line.startswith("+") and not line.startswith("+++"):
            lines_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            lines_removed += 1

    total_lines = lines_added + lines_removed
    total_files = len(files_changed)

    over_lines = total_lines > cfg.max_pr_lines
    over_files = total_files > cfg.max_pr_files

    if over_lines or over_files:
        conclusion = "action_required"
        problems = []
        if over_lines:
            problems.append(f"{total_lines} lines changed (max {cfg.max_pr_lines})")
        if over_files:
            problems.append(f"{total_files} files changed (max {cfg.max_pr_files})")
        title = "PR too large"
        summary = (
            f"Holy shit boys, this thing's huge. {' and '.join(problems)}.\n\n"
            f"Break it up into smaller PRs — it's not rocket appliances, "
            f"just split the work so people can actually fuckin' review it.\n\n"
            f"| Metric | Value | Limit |\n"
            f"|--------|-------|-------|\n"
            f"| Lines changed | {total_lines} | {cfg.max_pr_lines} |\n"
            f"| Files changed | {total_files} | {cfg.max_pr_files} |"
        )
    else:
        conclusion = "success"
        title = "PR size OK"
        summary = (
            f"Decent! {total_lines} lines across {total_files} files. "
            f"That's a reasonable size, boys.\n\n"
            f"| Metric | Value | Limit |\n"
            f"|--------|-------|-------|\n"
            f"| Lines changed | {total_lines} | {cfg.max_pr_lines} |\n"
            f"| Files changed | {total_files} | {cfg.max_pr_files} |"
        )

    await gh.create_check_run(
        owner, repo, ctx.installation_id,
        name="Ricky / Size Guard",
        head_sha=ctx.pr.head_sha,
        conclusion=conclusion,
        title=title,
        summary=summary,
    )

    log.info(
        "Size guard for PR #%d: %s (%d lines, %d files)",
        ctx.pr.number, conclusion, total_lines, total_files,
    )
