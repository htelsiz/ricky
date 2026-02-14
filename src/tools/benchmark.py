"""quick_benchmark — LLM-powered performance smell detection.

Scans the diff for common performance anti-patterns using Gemini.
Posts inline comments for issues found.
"""

from __future__ import annotations

import json
import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import build_diff_prompt, parse_diff, valid_lines_for_path
from ..gemini_client import _call_gemini
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()

_PERF_PROMPT = """\
You are Ricky LaFleur from Trailer Park Boys, analyzing code for performance problems.

Look for these specific anti-patterns in the changed lines:
- N+1 queries (database calls inside loops)
- O(n²) or worse algorithms (nested loops over same collection)
- Blocking I/O in async code (sync file/network calls in async functions)
- Unbounded queries (no LIMIT, fetching all rows)
- Large allocations in hot paths (creating big lists/dicts repeatedly)
- Missing pagination
- Unnecessary re-computation (same expensive call repeated)

Respond with JSON only. No markdown fences.

{
  "issues": [
    {
      "path": "src/example.py",
      "line": 42,
      "body": "Your Ricky-style explanation of the performance issue with a suggestion"
    }
  ]
}

If no performance issues found, return: {"issues": []}

Rules:
- "path" and "line" must EXACTLY match values from the changed lines below
- Only flag genuine performance concerns, not style issues
- Stay in character as Ricky
- Start each comment body with: ![medium](https://www.gstatic.com/codereviewagent/medium-priority.svg)"""


@tool(
    "quick_benchmark",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def quick_benchmark(data: dict) -> None:
    """Scan for performance anti-patterns."""
    pr = data["pull_request"]
    repo = data["repository"]
    installation_id = data["installation"]["id"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    pr_number = pr["number"]
    commit_sha = pr["head"]["sha"]

    diff = await _gh.fetch_diff(owner, repo_name, pr_number, installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    if not parsed:
        return

    structured = build_diff_prompt(parsed)

    raw = await _call_gemini(_PERF_PROMPT, f"Changed lines:\n{structured}")
    if not raw:
        return

    # Parse response
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

    try:
        result = json.loads(cleaned)
        issues = result.get("issues", [])
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse performance analysis response")
        return

    if not issues:
        return

    posted = 0
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        path = issue.get("path", "")
        line = issue.get("line", 0)
        body = issue.get("body", "")

        if not path or not line or not body:
            continue

        valid_lines = valid_lines_for_path(parsed, path)
        if line not in valid_lines:
            continue

        ok = await _gh.post_pr_comment(
            owner, repo_name, pr_number, installation_id,
            body=body,
            commit_id=commit_sha,
            path=path,
            line=line,
        )
        if ok:
            posted += 1

    if posted:
        logger.info("Posted %d performance comments on PR #%d", posted, pr_number)
