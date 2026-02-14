"""size_guard — PR size enforcement via GitHub Checks API.

Posts a pass/warn/fail check run based on lines changed and files changed.
"""

from __future__ import annotations

import logging

from ..clients.github import GitHubClient
from ..config import get_settings
from ..diff_parser import parse_diff
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()


@tool(
    "size_guard",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def size_guard(data: dict) -> None:
    """Check PR size and post a GitHub Check Run."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]

    cfg = get_settings().ricky

    # Fetch diff to count lines
    diff = await _gh.fetch_diff(owner, repo_name, pr_number, installation_id)
    if not diff:
        return

    # Count raw additions/deletions/files from the diff text
    lines_added = 0
    lines_removed = 0
    files_changed = set()

    for line in diff.split("\n"):
        if line.startswith("diff --git"):
            # Extract file path
            parts = line.split(" b/")
            if len(parts) > 1:
                files_changed.add(parts[-1])
        elif line.startswith("+") and not line.startswith("+++"):
            lines_added += 1
        elif line.startswith("-") and not line.startswith("---"):
            lines_removed += 1

    total_lines = lines_added + lines_removed
    total_files = len(files_changed)

    # Determine verdict
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

    await _gh.create_check_run(
        owner, repo_name, installation_id,
        name="Ricky / Size Guard",
        head_sha=head_sha,
        conclusion=conclusion,
        title=title,
        summary=summary,
    )

    logger.info(
        "Size guard for PR #%d: %s (%d lines, %d files)",
        pr_number, conclusion, total_lines, total_files,
    )
