"""todo_tracker — find new TODO/FIXME/HACK/XXX in PRs and create GitHub Issues.

Scans the diff for added lines containing TODO markers. Optionally creates
a GitHub Issue for each one, linked to the exact file and line.
"""

from __future__ import annotations

import logging
import re

from ..clients.github import GitHubClient
from ..config import get_settings
from ..diff_parser import parse_diff
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

# Match TODO, FIXME, HACK, XXX (with optional colon and message)
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b\s*:?\s*(.*)", re.IGNORECASE)


@tool(
    "todo_tracker",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
    commands=["@ricky todos"],
)
async def todo_tracker(data: dict) -> None:
    """Scan diff for new TODO/FIXME/HACK/XXX and optionally create issues."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    head_sha = pr["head"]["sha"]
    head_ref = pr["head"]["ref"]

    cfg = get_settings().ricky

    # Fetch and parse diff
    diff = await _gh.fetch_diff(owner, repo_name, pr_number, installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    if not parsed:
        return

    # Find TODOs in added lines only
    todos: list[dict] = []
    for file_info in parsed:
        for line_info in file_info["lines"]:
            if line_info["type"] != "add":
                continue
            match = _TODO_RE.search(line_info["content"])
            if match:
                todos.append({
                    "path": file_info["path"],
                    "line": line_info["number"],
                    "tag": match.group(1).upper(),
                    "text": match.group(2).strip() or "(no description)",
                })

    if not todos:
        logger.info("No new TODOs in PR #%d", pr_number)
        return

    logger.info("Found %d new TODO(s) in PR #%d", len(todos), pr_number)

    # Create issues if enabled
    created = 0
    if cfg.todo_create_issues:
        for t in todos:
            link = f"https://github.com/{owner}/{repo_name}/blob/{head_sha}/{t['path']}#L{t['line']}"
            issue_body = (
                f"Found `{t['tag']}` in [{t['path']}:{t['line']}]({link}):\n\n"
                f"> {t['text']}\n\n"
                f"From PR #{pr_number} (`{head_ref}`)."
            )
            result = await _gh.create_issue(
                owner, repo_name, installation_id,
                title=f"{t['tag']}: {t['text'][:80]}",
                body=issue_body,
                labels=["tech-debt"],
            )
            if result:
                created += 1

        logger.info("Created %d issue(s) from TODOs in PR #%d", created, pr_number)

    # Post a summary comment on the PR
    summary_lines = [f"**Found {len(todos)} new TODO(s) in this PR, boys.**\n"]
    for t in todos:
        issue_note = ""
        summary_lines.append(f"- `{t['tag']}` in `{t['path']}:{t['line']}` — {t['text']}{issue_note}")

    if cfg.todo_create_issues and created > 0:
        summary_lines.append(f"\nCreated {created} issue(s) so nobody fuckin' forgets about them.")
    else:
        summary_lines.append(
            "\nStop saying you'll do it later and just do it. "
            "These TODOs are just sitting there like Corey and Trevor with nothing to do."
        )

    await _gh.post_issue_comment(
        owner, repo_name, pr_number, installation_id,
        body="\n".join(summary_lines),
    )
