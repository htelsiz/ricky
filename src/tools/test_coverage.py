"""test_coverage_check — detect functions/methods lacking test coverage."""

import logging
import re

from ..clients.github import GitHubClient
from ..diff_parser import parse_diff
from ..models.github import WebhookContext
from ._registry import tool

log = logging.getLogger(__name__)

_FUNC_PATTERNS = [
    re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\("),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
    re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
    re.compile(r"^\s*func\s+(\w+)\s*\("),
]

_TEST_PATTERNS = [
    "{base}_test.py", "test_{base}.py",
    "{base}.test.ts", "{base}.test.js", "{base}.spec.ts", "{base}.spec.js",
    "{base}_test.go",
    "{base}_test.rs",
]


@tool(
    "test_coverage_check",
    events=["pull_request"],
    actions=["opened", "synchronize", "reopened"],
)
async def test_coverage_check(ctx: WebhookContext) -> None:
    """Check if new functions have corresponding tests."""
    assert ctx.pr is not None
    gh = GitHubClient.from_env()

    owner = ctx.repo.owner
    repo = ctx.repo.name

    diff = await gh.fetch_diff(owner, repo, ctx.pr.number, ctx.installation_id)
    if not diff:
        return

    parsed = parse_diff(diff)
    if not parsed:
        return

    untested: list[dict] = []
    test_files_in_pr: set[str] = set()

    for file_info in parsed:
        path = file_info["path"]
        if _is_test_file(path):
            test_files_in_pr.add(path)
            continue

        if not _is_source_file(path):
            continue

        for line_info in file_info["lines"]:
            if line_info["type"] != "add":
                continue
            func_name = _extract_func_name(line_info["content"])
            if func_name and not func_name.startswith("_"):
                untested.append({
                    "path": path,
                    "line": line_info["number"],
                    "func": func_name,
                })

    if not untested:
        return

    tested_files: set[str] = set()
    for test_path in test_files_in_pr:
        for src_item in untested:
            if _test_covers_source(test_path, src_item["path"]):
                tested_files.add(src_item["path"])

    gaps = [u for u in untested if u["path"] not in tested_files]
    if not gaps:
        return

    lines = [f"**Did anyone even fuckin' test this?** Found {len(gaps)} new function(s) with no tests:\n"]
    for g in gaps:
        lines.append(f"- `{g['func']}` in `{g['path']}:{g['line']}`")

    lines.append(
        "\nListen, I'm not saying everything needs a test, but if it's public "
        "and you wrote it fresh, at least throw a basic test on it. "
        "It's not rocket appliances."
    )

    await gh.post_issue_comment(
        owner, repo, ctx.pr.number, ctx.installation_id,
        body="\n".join(lines),
    )

    log.info("Test coverage: %d untested functions in PR #%d", len(gaps), ctx.pr.number)


def _is_test_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return any(p in name for p in ["test_", "_test.", ".test.", ".spec."])


def _is_source_file(path: str) -> bool:
    return path.endswith((".py", ".ts", ".js", ".go", ".rs", ".tsx", ".jsx"))


def _extract_func_name(line: str) -> str | None:
    for pat in _FUNC_PATTERNS:
        m = pat.search(line)
        if m:
            return m.group(1)
    return None


def _test_covers_source(test_path: str, source_path: str) -> bool:
    src_base = source_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    test_name = test_path.rsplit("/", 1)[-1].lower()
    return src_base.lower() in test_name
