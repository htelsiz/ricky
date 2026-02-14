"""merge_conflict_resolver — detect and comment on merge conflicts.

When a PR has merge conflicts, posts analysis and resolution suggestions.
"""

from __future__ import annotations

import logging

from ..clients.github import GitHubClient
from ..gemini_client import _call_gemini
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

_CONFLICT_PROMPT = """\
You are Ricky LaFleur from Trailer Park Boys. A PR has merge conflicts.

Given the conflicting files listed below, explain in 2-3 sentences what
probably happened (who changed what) and suggest how to resolve it.
Stay in character. Use Rickyisms. Keep it practical."""


@tool(
    "merge_conflict_resolver",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def merge_conflict_resolver(data: dict) -> None:
    """Check for merge conflicts and post resolution advice."""
    pr = data["pull_request"]

    # GitHub tells us if mergeable
    mergeable = pr.get("mergeable")
    # mergeable can be None (not yet computed), True, or False
    if mergeable is not False:
        return

    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    base_ref = pr.get("base", {}).get("ref", "main")
    head_ref = pr.get("head", {}).get("ref", "unknown")

    logger.info("PR #%d has merge conflicts", pr_number)

    # Get the list of conflicting files from the PR
    resp = await _gh.request(
        "GET",
        f"/repos/{owner}/{repo_name}/pulls/{pr_number}/files",
        installation_id,
    )
    if resp.status_code != 200:
        return

    files = resp.json()
    file_list = [f.get("filename", "") for f in files[:20]]

    diagnosis = await _call_gemini(
        _CONFLICT_PROMPT,
        f"PR #{pr_number}: merging `{head_ref}` into `{base_ref}`\n\n"
        f"Files in this PR:\n" + "\n".join(f"- {f}" for f in file_list),
    )

    if not diagnosis:
        return

    comment = (
        f"**Everyone's stepping on each other's dicks here, boys.**\n\n"
        f"This PR has merge conflicts with `{base_ref}`.\n\n"
        f"{diagnosis}\n\n"
        f"To fix it:\n"
        f"```bash\n"
        f"git checkout {head_ref}\n"
        f"git merge {base_ref}\n"
        f"# resolve conflicts\n"
        f"git add . && git commit\n"
        f"git push\n"
        f"```"
    )

    await _gh.post_issue_comment(
        owner, repo_name, pr_number, installation_id,
        body=comment,
    )
