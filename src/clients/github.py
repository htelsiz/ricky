"""Full GitHub API client — extracts all inline API calls into one place."""

from __future__ import annotations

import logging

import httpx

from .._base_auth import get_installation_token
from ._base import BaseClient

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


class GitHubClient(BaseClient):
    """Authenticated GitHub API client using installation tokens."""

    def __init__(self):
        super().__init__(GITHUB_API)

    async def request(
        self,
        method: str,
        path: str,
        installation_id: int,
        *,
        accept: str = "application/vnd.github+json",
        **kwargs,
    ) -> httpx.Response:
        token = await get_installation_token(installation_id)
        return await self._request(method, path, token, accept=accept, **kwargs)

    # ── Diffs ──────────────────────────────────────────────────────────

    async def fetch_diff(self, owner: str, repo: str, pr_number: int, installation_id: int) -> str:
        resp = await self.request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            installation_id,
            accept="application/vnd.github.diff",
        )
        if resp.status_code != 200:
            logger.error("Failed to fetch diff: %d", resp.status_code)
            return ""
        return resp.text

    # ── File contents ──────────────────────────────────────────────────

    async def fetch_file_raw(
        self, owner: str, repo: str, path: str, ref: str, installation_id: int
    ) -> str:
        resp = await self.request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}?ref={ref}",
            installation_id,
            accept="application/vnd.github.raw+json",
        )
        if resp.status_code == 200:
            return resp.text
        return ""

    # ── Pull request comments (individual, per-line) ───────────────────

    async def post_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
        *,
        body: str,
        commit_id: str,
        path: str,
        line: int,
        side: str = "RIGHT",
    ) -> bool:
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/comments",
            installation_id,
            json={
                "body": body,
                "commit_id": commit_id,
                "path": path,
                "line": line,
                "side": side,
            },
        )
        if resp.status_code in (200, 201):
            return True
        logger.warning("Failed to post comment on %s:%d: %d %s", path, line, resp.status_code, resp.text)
        return False

    # ── Pull request reviews (summary) ────────────────────────────────

    async def post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
        *,
        commit_id: str,
        body: str,
        event: str = "COMMENT",
    ) -> bool:
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            installation_id,
            json={"commit_id": commit_id, "body": body, "event": event},
        )
        if resp.status_code in (200, 201):
            return True
        logger.error("Failed to post review: %d %s", resp.status_code, resp.text)
        return False

    # ── Issue / PR comments (generic) ─────────────────────────────────

    async def post_issue_comment(
        self, owner: str, repo: str, issue_number: int, installation_id: int, *, body: str
    ) -> bool:
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            installation_id,
            json={"body": body},
        )
        if resp.status_code in (200, 201):
            return True
        logger.error("Failed to post comment: %d %s", resp.status_code, resp.text)
        return False

    # ── Labels ────────────────────────────────────────────────────────

    async def add_labels(
        self, owner: str, repo: str, issue_number: int, installation_id: int, labels: list[str]
    ) -> bool:
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            installation_id,
            json={"labels": labels},
        )
        return resp.status_code in (200, 201)

    # ── Check Runs ────────────────────────────────────────────────────

    async def create_check_run(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        *,
        name: str,
        head_sha: str,
        status: str = "completed",
        conclusion: str = "success",
        title: str = "",
        summary: str = "",
    ) -> bool:
        payload: dict = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
            "conclusion": conclusion,
        }
        if title or summary:
            payload["output"] = {"title": title, "summary": summary}
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/check-runs",
            installation_id,
            json=payload,
        )
        if resp.status_code in (200, 201):
            return True
        logger.error("Failed to create check run: %d %s", resp.status_code, resp.text)
        return False

    # ── Issues ────────────────────────────────────────────────────────

    async def create_issue(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        *,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict | None:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            installation_id,
            json=payload,
        )
        if resp.status_code in (200, 201):
            return resp.json()
        logger.error("Failed to create issue: %d %s", resp.status_code, resp.text)
        return None

    # ── Actions / CI logs ─────────────────────────────────────────────

    async def get_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, installation_id: int
    ) -> list[dict]:
        resp = await self.request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{ref}/check-runs",
            installation_id,
        )
        if resp.status_code == 200:
            return resp.json().get("check_runs", [])
        return []

    async def download_workflow_logs(
        self, owner: str, repo: str, run_id: int, installation_id: int
    ) -> str:
        resp = await self.request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            installation_id,
        )
        if resp.status_code == 200:
            return resp.text
        logger.warning("Failed to download logs for run %d: %d", run_id, resp.status_code)
        return ""

    # ── Trees / blobs (for file listing) ──────────────────────────────

    async def get_tree(
        self, owner: str, repo: str, tree_sha: str, installation_id: int, *, recursive: bool = True
    ) -> list[dict]:
        params = "?recursive=1" if recursive else ""
        resp = await self.request(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{tree_sha}{params}",
            installation_id,
        )
        if resp.status_code == 200:
            return resp.json().get("tree", [])
        return []

    # ── Refs / branches ───────────────────────────────────────────────

    async def create_branch(
        self, owner: str, repo: str, branch_name: str, sha: str, installation_id: int
    ) -> bool:
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            installation_id,
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )
        return resp.status_code in (200, 201)

    async def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        installation_id: int,
        *,
        content_b64: str,
        message: str,
        branch: str,
        sha: str | None = None,
    ) -> bool:
        payload: dict = {
            "message": message,
            "content": content_b64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        resp = await self.request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            installation_id,
            json=payload,
        )
        return resp.status_code in (200, 201)

    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        *,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> dict | None:
        resp = await self.request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            installation_id,
            json={"title": title, "body": body, "head": head, "base": base},
        )
        if resp.status_code in (200, 201):
            return resp.json()
        logger.error("Failed to create PR: %d %s", resp.status_code, resp.text)
        return None
