"""dead_code_hunter — detect unused imports and unreferenced code in diffs."""

import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

_PYTHON_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+\S+\s+)?import\s+(?:.*\bas\s+)?(\w+)", re.MULTILINE
)


@tool(
    "dead_code_hunter",
    events=["issue_comment"],
    actions=["created"],
    commands=["@ricky dead-code"],
)
async def dead_code_command(ctx: WebhookContext) -> None:
    """Scan for dead code when someone asks @ricky dead-code."""
    if ctx.comment is None or ctx.issue is None:
        return

    if "@ricky" not in ctx.comment.body.lower() or "dead-code" not in ctx.comment.body.lower():
        return

    gh = GitHubClient.from_env()
    owner = ctx.repo.owner
    repo = ctx.repo.name

    if not ctx.issue.has_pull_request:
        await gh.post_issue_comment(
            owner, repo, ctx.issue.number, ctx.installation_id,
            body="Boys, I need a PR to check for dead code. This is just an issue.",
        )
        return

    diff = await gh.fetch_diff(owner, repo, ctx.issue.number, ctx.installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    findings = _analyze_dead_code(parsed)

    if not findings:
        await gh.post_issue_comment(
            owner, repo, ctx.issue.number, ctx.installation_id,
            body="Decent! Didn't find any dead code sitting around like Corey and Trevor.",
        )
        return

    lines = [f"**Found {len(findings)} dead code suspect(s), boys:**\n"]
    for f in findings:
        lines.append(f"- `{f['name']}` in `{f['path']}:{f['line']}` — {f['reason']}")

    lines.append(
        "\nThis code's just sitting there doing nothing. Either use it or lose it."
    )

    await gh.post_issue_comment(
        owner, repo, ctx.issue.number, ctx.installation_id,
        body="\n".join(lines),
    )


def _analyze_dead_code(parsed: list[dict]) -> list[dict]:
    """Simple heuristic dead code analysis on parsed diff data."""
    findings = []

    for file_info in parsed:
        path = file_info["path"]
        if not path.endswith(".py"):
            continue

        added_lines = [l for l in file_info["lines"] if l["type"] == "add"]
        all_content = " ".join(l["content"] for l in file_info["lines"])

        for line_info in added_lines:
            content = line_info["content"]

            m = _PYTHON_IMPORT_RE.match(content)
            if m:
                name = m.group(1)
                rest = all_content.replace(content, "", 1)
                if re.search(rf"\b{re.escape(name)}\b", rest) is None:
                    findings.append({
                        "path": path,
                        "line": line_info["number"],
                        "name": name,
                        "reason": "imported but never used in this diff",
                    })

            if content.strip() == "pass":
                findings.append({
                    "path": path,
                    "line": line_info["number"],
                    "name": "pass",
                    "reason": "empty placeholder — implement or remove",
                })

    return findings
