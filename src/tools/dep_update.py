"""dependency_update_bot — check for outdated packages.

Triggered by @ricky outdated command. Checks package registries
and posts a report of outdated dependencies.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from ..clients.github import GitHubClient
from ._registry import tool

logger = logging.getLogger(__name__)

_gh = GitHubClient()


@tool(
    "dependency_update_bot",
    events=["issue_comment"],
    actions=["created"],
    commands=["@ricky outdated"],
)
async def dependency_update_bot(data: dict) -> None:
    """Check for outdated packages when asked."""
    comment = data["comment"]
    body = comment.get("body", "")

    if "@ricky" not in body.lower() or "outdated" not in body.lower():
        return

    repo = data["repository"]
    installation_id = data["installation"]["id"]
    issue = data["issue"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    issue_number = issue["number"]

    logger.info("Checking outdated deps for %s/%s", owner, repo_name)

    # Try to fetch pyproject.toml
    pyproject = await _gh.fetch_file_raw(
        owner, repo_name, "pyproject.toml", "main", installation_id
    )

    # Try to fetch package.json
    package_json = await _gh.fetch_file_raw(
        owner, repo_name, "package.json", "main", installation_id
    )

    outdated = []

    if pyproject:
        outdated.extend(await _check_python_deps(pyproject))

    if package_json:
        outdated.extend(await _check_npm_deps(package_json))

    if not pyproject and not package_json:
        await _gh.post_issue_comment(
            owner, repo_name, issue_number, installation_id,
            body="Couldn't find pyproject.toml or package.json in this repo, boys.",
        )
        return

    if not outdated:
        await _gh.post_issue_comment(
            owner, repo_name, issue_number, installation_id,
            body="Your shit's all up to date, boys. Decent!",
        )
        return

    lines = [f"**Your shit's out of date, boys.** Found {len(outdated)} outdated package(s):\n"]
    lines.append("| Package | Current | Latest | Ecosystem |")
    lines.append("|---------|---------|--------|-----------|")
    for dep in outdated:
        lines.append(f"| {dep['name']} | {dep['current']} | {dep['latest']} | {dep['ecosystem']} |")

    lines.append(
        "\nMight want to update these. It's like driving the shit-mobile "
        "without changing the oil — eventually it's gonna break down."
    )

    await _gh.post_issue_comment(
        owner, repo_name, issue_number, installation_id,
        body="\n".join(lines),
    )


async def _check_python_deps(pyproject: str) -> list[dict]:
    """Check Python dependencies against PyPI."""
    outdated = []

    # Extract dependencies from pyproject.toml
    deps_match = re.search(r'dependencies\s*=\s*\[(.*?)\]', pyproject, re.DOTALL)
    if not deps_match:
        return []

    deps_text = deps_match.group(1)
    dep_pattern = re.compile(r'"([a-zA-Z0-9_-]+)(?:\[.*?\])?>=?([0-9.]+)"')

    for match in dep_pattern.finditer(deps_text):
        name = match.group(1)
        current = match.group(2)

        latest = await _get_pypi_latest(name)
        if latest and latest != current and not current.startswith(latest):
            outdated.append({
                "name": name,
                "current": f">={current}",
                "latest": latest,
                "ecosystem": "PyPI",
            })

    return outdated


async def _check_npm_deps(package_json_text: str) -> list[dict]:
    """Check npm dependencies against the registry."""
    outdated = []

    try:
        pkg = json.loads(package_json_text)
    except json.JSONDecodeError:
        return []

    all_deps = {}
    all_deps.update(pkg.get("dependencies", {}))
    all_deps.update(pkg.get("devDependencies", {}))

    for name, version_spec in list(all_deps.items())[:20]:  # Cap at 20
        current = re.sub(r"[\^~>=<]", "", version_spec)
        latest = await _get_npm_latest(name)
        if latest and latest != current:
            outdated.append({
                "name": name,
                "current": version_spec,
                "latest": latest,
                "ecosystem": "npm",
            })

    return outdated


async def _get_pypi_latest(name: str) -> str:
    """Get latest version from PyPI."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://pypi.org/pypi/{name}/json", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("info", {}).get("version", "")
    except Exception:
        pass
    return ""


async def _get_npm_latest(name: str) -> str:
    """Get latest version from npm registry."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"https://registry.npmjs.org/{name}/latest", timeout=10.0)
            if resp.status_code == 200:
                return resp.json().get("version", "")
    except Exception:
        pass
    return ""
