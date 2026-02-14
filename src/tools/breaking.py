"""breaking_change_detector — detect API contract violations in PRs.

Scans the diff for changed function signatures, removed exports,
modified API routes, and schema changes. Posts warnings.
"""

from __future__ import annotations

import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

# Patterns that suggest breaking changes in removed lines (context or removed)
_BREAKING_PATTERNS = [
    # Python: function signature changes
    (re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\("), "function signature"),
    # Python: class definition removed
    (re.compile(r"^\s*class\s+(\w+)"), "class definition"),
    # JS/TS: export removed
    (re.compile(r"^\s*export\s+(?:default\s+)?(?:function|class|const|let|var)\s+(\w+)"), "export"),
    # API routes
    (re.compile(r"""(?:@app\.(?:get|post|put|delete|patch)|router\.(?:get|post|put|delete|patch))\s*\(\s*["']([^"']+)"""), "API route"),
    # Go: exported function
    (re.compile(r"^\s*func\s+([A-Z]\w+)\s*\("), "exported function"),
]


@tool(
    "breaking_change_detector",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def breaking_change_detector(data: dict) -> None:
    """Detect potential breaking changes in the PR."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]

    diff = await _gh.fetch_diff(owner, repo_name, pr_number, installation_id)
    if not diff:
        return

    # Parse the raw diff to find removed lines (not available in parse_diff which only tracks additions)
    breaking = _scan_for_breaking_changes(diff)

    if not breaking:
        return

    lines = [
        "**You can't just change shit without telling people, boys.**\n",
        "Detected potential breaking changes:\n",
    ]
    for b in breaking:
        lines.append(f"- **{b['type']}**: `{b['name']}` in `{b['path']}` was {b['change']}")

    lines.append(
        "\nIf this is intentional, make sure to:\n"
        "1. Bump the version number\n"
        "2. Update the changelog\n"
        "3. Let consumers know what changed"
    )

    await _gh.post_issue_comment(
        owner, repo_name, pr_number, installation_id,
        body="\n".join(lines),
    )

    logger.info("Found %d potential breaking change(s) in PR #%d", len(breaking), pr_number)


def _scan_for_breaking_changes(raw_diff: str) -> list[dict]:
    """Scan raw diff for removed/changed public API surface."""
    findings = []
    current_file = ""

    for line in raw_diff.split("\n"):
        # Track current file
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue

        # Only look at removed lines
        if not line.startswith("-") or line.startswith("---"):
            continue

        content = line[1:]  # Strip the - prefix

        for pattern, change_type in _BREAKING_PATTERNS:
            m = pattern.search(content)
            if m:
                name = m.group(1)
                # Check if this was actually modified (re-added with changes) vs removed
                findings.append({
                    "path": current_file,
                    "name": name,
                    "type": change_type,
                    "change": "removed or modified",
                })
                break

    # Deduplicate by (path, name)
    seen = set()
    unique = []
    for f in findings:
        key = (f["path"], f["name"])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique
