"""todo_tracker — find new TODO/FIXME/HACK/XXX in PRs and create GitHub Issues."""

import logging
import re

from ..clients.github import GitHubClient
from ..config import RickySettings
from ..diff_parser import parse_diff
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b\s*:?\s*(.*)", re.IGNORECASE)


@tool(
    "todo_tracker",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
    commands=["@ricky todos"],
)
async def todo_tracker(ctx: WebhookContext) -> None:
    """Scan diff for new TODO/FIXME/HACK/XXX and optionally create issues."""
    assert ctx.pr is not None
    gh = GitHubClient.from_env()
    cfg = RickySettings()  # type: ignore[call-arg]

    owner = ctx.repo.owner
    repo = ctx.repo.name

    diff = await gh.fetch_diff(owner, repo, ctx.pr.number, ctx.installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    if not parsed:
        return

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
        log.info("No new TODOs in PR #%d", ctx.pr.number)
        return

    log.info("Found %d new TODO(s) in PR #%d", len(todos), ctx.pr.number)

    created = 0
    if cfg.todo_create_issues:
        for t in todos:
            link = f"https://github.com/{owner}/{repo}/blob/{ctx.pr.head_sha}/{t['path']}#L{t['line']}"
            issue_body = (
                f"Found `{t['tag']}` in [{t['path']}:{t['line']}]({link}):\n\n"
                f"> {t['text']}\n\n"
                f"From PR #{ctx.pr.number} (`{ctx.pr.head_ref}`)."
            )
            try:
                await gh.create_issue(
                    owner, repo, ctx.installation_id,
                    title=f"{t['tag']}: {t['text'][:80]}",
                    body=issue_body,
                    labels=["tech-debt"],
                )
                created += 1
            except Exception:
                log.warning("Failed to create issue for %s:%d", t["path"], t["line"])

        log.info("Created %d issue(s) from TODOs in PR #%d", created, ctx.pr.number)

    summary_lines = [f"**Found {len(todos)} new TODO(s) in this PR, boys.**\n"]
    for t in todos:
        summary_lines.append(f"- `{t['tag']}` in `{t['path']}:{t['line']}` — {t['text']}")

    if cfg.todo_create_issues and created > 0:
        summary_lines.append(f"\nCreated {created} issue(s) so nobody fuckin' forgets about them.")
    else:
        summary_lines.append(
            "\nStop saying you'll do it later and just do it. "
            "These TODOs are just sitting there like Corey and Trevor with nothing to do."
        )

    await gh.post_issue_comment(
        owner, repo, ctx.pr.number, ctx.installation_id,
        body="\n".join(summary_lines),
    )
