"""dead_code_hunter — detect unused imports and unreferenced code in diffs.

Uses simple heuristic analysis (not full AST) to flag likely dead code
in changed files. Triggered by @ricky dead-code or during PR review.
"""

from __future__ import annotations

import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

# Python unused import detection
_PYTHON_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+\S+\s+)?import\s+(?:.*\bas\s+)?(\w+)", re.MULTILINE
)


@tool(
    "dead_code_hunter",
    events=["issue_comment"],
    actions=["created"],
    commands=["@ricky dead-code"],
)
async def dead_code_command(data: dict) -> None:
    """Scan for dead code when someone asks @ricky dead-code."""
    comment = data["comment"]
    body = comment.get("body", "")

    if "@ricky" not in body.lower() or "dead-code" not in body.lower():
        return

    issue = data["issue"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    issue_number = issue["number"]

    if "pull_request" not in issue:
        await _gh.post_issue_comment(
            owner, repo_name, issue_number, installation_id,
            body="Boys, I need a PR to check for dead code. This is just an issue.",
        )
        return

    # Fetch the PR diff
    diff = await _gh.fetch_diff(owner, repo_name, issue_number, installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    findings = _analyze_dead_code(parsed)

    if not findings:
        await _gh.post_issue_comment(
            owner, repo_name, issue_number, installation_id,
            body="Decent! Didn't find any dead code sitting around like Corey and Trevor.",
        )
        return

    lines = [f"**Found {len(findings)} dead code suspect(s), boys:**\n"]
    for f in findings:
        lines.append(f"- `{f['name']}` in `{f['path']}:{f['line']}` — {f['reason']}")

    lines.append(
        "\nThis code's just sitting there doing nothing. Either use it or lose it."
    )

    await _gh.post_issue_comment(
        owner, repo_name, issue_number, installation_id,
        body="\n".join(lines),
    )


def _analyze_dead_code(parsed: list[dict]) -> list[dict]:
    """Simple heuristic dead code analysis on parsed diff data."""
    findings = []

    for file_info in parsed:
        path = file_info["path"]
        if not path.endswith(".py"):
            continue

        # Collect all added content for this file
        added_lines = [l for l in file_info["lines"] if l["type"] == "add"]
        all_content = " ".join(l["content"] for l in file_info["lines"])

        for line_info in added_lines:
            content = line_info["content"]

            # Check for unused imports (simple: imported name not found elsewhere)
            m = _PYTHON_IMPORT_RE.match(content)
            if m:
                name = m.group(1)
                # Count occurrences of the name in all file content (beyond the import)
                rest = all_content.replace(content, "", 1)
                if re.search(rf"\b{re.escape(name)}\b", rest) is None:
                    findings.append({
                        "path": path,
                        "line": line_info["number"],
                        "name": name,
                        "reason": "imported but never used in this diff",
                    })

            # Check for `pass` in function/class bodies (placeholder code)
            if content.strip() == "pass":
                findings.append({
                    "path": path,
                    "line": line_info["number"],
                    "name": "pass",
                    "reason": "empty placeholder — implement or remove",
                })

    return findings
