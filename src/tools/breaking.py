"""breaking_change_detector — detect API contract violations in PRs.

Scans the diff for changed function signatures, removed exports,
modified API routes, and schema changes. Posts warnings.
"""

import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

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
async def breaking_change_detector(ctx: WebhookContext) -> None:
    """Detect potential breaking changes in the PR."""
    assert ctx.pr is not None
    gh = GitHubClient.from_env()

    owner = ctx.repo.owner
    repo = ctx.repo.name

    diff = await gh.fetch_diff(owner, repo, ctx.pr.number, ctx.installation_id)
    if not diff:
        return

    # Parse the raw diff to find removed lines
    parsed = parse_diff(diff)
    if not parsed:
        return

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

    await gh.post_issue_comment(
        owner, repo, ctx.pr.number, ctx.installation_id,
        body="\n".join(lines),
    )

    log.info("Found %d potential breaking change(s) in PR #%d", len(breaking), ctx.pr.number)


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
                findings.append({
                    "path": current_file,
                    "name": name,
                    "type": change_type,
                    "change": "removed or modified",
                })
                break

    # Deduplicate by (path, name)
    seen: set[tuple[str, str]] = set()
    unique = []
    for f in findings:
        key = (f["path"], f["name"])
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique
