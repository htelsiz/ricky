"""git_blame_context — surface change history for heavily modified files.

Checks which files in the PR have been changed frequently (hot files)
and posts context about the change history.
"""

from __future__ import annotations

import logging

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

# Threshold: if a file appears in >N recent commits, flag as hot
HOT_FILE_THRESHOLD = 10


@tool(
    "git_blame_context",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def git_blame_context(data: dict) -> None:
    """Identify hot files and surface change history context."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]

    diff = await _gh.fetch_diff(owner, repo_name, pr_number, installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    if not parsed:
        return

    # Only analyze if there are enough files to make this interesting
    if len(parsed) < 2:
        return

    # Check commit history for each file to find hot files
    hot_files = []
    for file_info in parsed:
        path = file_info["path"]
        resp = await _gh.request(
            "GET",
            f"/repos/{owner}/{repo_name}/commits",
            installation_id,
            params={"path": path, "per_page": 20},
        )
        if resp.status_code != 200:
            continue

        commits = resp.json()
        if len(commits) >= HOT_FILE_THRESHOLD:
            # Get the most recent committer
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

    await _gh.post_issue_comment(
        owner, repo_name, pr_number, installation_id,
        body="\n".join(lines),
    )

    logger.info("Found %d hot file(s) in PR #%d", len(hot_files), pr_number)
