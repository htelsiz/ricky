"""GitHub App client — JWT auth, installation tokens, typed API methods."""

import logging
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

from ..config import GithubSettings
from ..errors import ApiResponseError, AuthenticationError, NotFoundError

log = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubClient:
    """Async GitHub API client using App installation tokens."""

    service_name = "github"

    def __init__(self, settings: GithubSettings) -> None:
        self._settings = settings
        self._app_id: str | None = None
        self._private_key: bytes | None = None
        self._install_tokens: dict[int, tuple[str, float]] = {}

    @classmethod
    def from_env(cls) -> "GitHubClient":
        return cls(GithubSettings())  # type: ignore[call-arg]

    # -- auth internals -------------------------------------------------------

    def _get_app_id(self) -> str:
        if self._app_id is None:
            self._app_id = Path(self._settings.app_id_file).read_text().strip()
        return self._app_id

    def _get_private_key(self) -> bytes:
        if self._private_key is None:
            self._private_key = Path(self._settings.private_key_file).read_bytes()
        return self._private_key

    def _generate_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 600, "iss": self._get_app_id()}
        return jwt.encode(payload, self._get_private_key(), algorithm="RS256")

    async def _get_token(self, installation_id: int) -> str:
        cached = self._install_tokens.get(installation_id)
        if cached and time.time() < cached[1]:
            return cached[0]

        app_jwt = self._generate_jwt()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": API_VERSION,
                },
            )
        self._handle_response(resp)
        data = resp.json()
        token = data["token"]
        self._install_tokens[installation_id] = (token, time.time() + 3300)
        return token

    # -- response handling ----------------------------------------------------

    def _handle_response(self, resp: httpx.Response) -> None:
        if resp.status_code == 401:
            raise AuthenticationError(self.service_name, "bad token")
        if resp.status_code == 404:
            raise NotFoundError(self.service_name, str(resp.url))
        if resp.status_code >= 400:
            raise ApiResponseError(self.service_name, resp.status_code, resp.text)

    # -- low-level request ----------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        installation_id: int,
        accept: str = "application/vnd.github+json",
        **kwargs: Any,
    ) -> httpx.Response:
        token = await self._get_token(installation_id)
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method,
                f"{GITHUB_API}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": accept,
                    "X-GitHub-Api-Version": API_VERSION,
                },
                timeout=30.0,
                **kwargs,
            )
        self._handle_response(resp)
        return resp

    # -- typed API methods ----------------------------------------------------

    async def fetch_diff(
        self, owner: str, repo: str, pr_number: int, installation_id: int,
    ) -> str:
        """Fetch a PR diff. Raises on error."""
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            installation_id,
            accept="application/vnd.github.diff",
        )
        return resp.text

    async def fetch_file_raw(
        self, owner: str, repo: str, path: str, ref: str, installation_id: int,
    ) -> str | None:
        """Fetch raw file content at a given ref. Returns None if not found."""
        try:
            resp = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path}?ref={ref}",
                installation_id,
                accept="application/vnd.github.raw+json",
            )
            return resp.text
        except NotFoundError:
            return None

    async def fetch_file_content(
        self, owner: str, repo: str, path: str, installation_id: int,
    ) -> str | None:
        """Fetch raw file content (default branch). Returns None if not found."""
        try:
            resp = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path}",
                installation_id,
                accept="application/vnd.github.raw+json",
            )
            return resp.text
        except NotFoundError:
            return None

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
    ) -> None:
        """Post an inline review comment on a specific line. Raises on error."""
        await self._request(
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

    async def post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
        *,
        body: str,
        commit_id: str = "",
        event: str = "COMMENT",
    ) -> None:
        """Post a PR review. Raises on error."""
        payload: dict[str, str] = {"body": body, "event": event}
        if commit_id:
            payload["commit_id"] = commit_id
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            installation_id,
            json=payload,
        )
        log.info("Posted review on PR #%d", pr_number)

    async def post_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: int,
        *,
        body: str,
    ) -> None:
        """Post an issue/PR comment. Raises on error."""
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            installation_id,
            json={"body": body},
        )
        log.info("Posted comment on #%d", issue_number)

    async def add_labels(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        installation_id: int,
        labels: list[str],
    ) -> None:
        """Add labels to an issue/PR. Raises on error."""
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            installation_id,
            json={"labels": labels},
        )

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
    ) -> None:
        """Create a check run. Raises on error."""
        payload: dict = {
            "name": name,
            "head_sha": head_sha,
            "status": status,
            "conclusion": conclusion,
        }
        if title or summary:
            payload["output"] = {"title": title, "summary": summary}
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/check-runs",
            installation_id,
            json=payload,
        )

    async def create_issue(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        *,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        """Create an issue. Returns the response JSON. Raises on error."""
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            installation_id,
            json=payload,
        )
        return resp.json()

    async def get_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, installation_id: int,
    ) -> list[dict]:
        """Get check runs for a git ref. Returns empty list on error."""
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{ref}/check-runs",
            installation_id,
        )
        return resp.json().get("check_runs", [])

    async def download_workflow_logs(
        self, owner: str, repo: str, run_id: int, installation_id: int,
    ) -> str:
        """Download logs for a workflow run. Returns empty string on not found."""
        try:
            resp = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
                installation_id,
            )
            return resp.text
        except (NotFoundError, ApiResponseError):
            log.warning("Failed to download logs for run %d", run_id)
            return ""

    async def get_tree(
        self,
        owner: str,
        repo: str,
        tree_sha: str,
        installation_id: int,
        *,
        recursive: bool = True,
    ) -> list[dict]:
        """Get a git tree. Returns empty list on error."""
        params = "?recursive=1" if recursive else ""
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{tree_sha}{params}",
            installation_id,
        )
        return resp.json().get("tree", [])

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        sha: str,
        installation_id: int,
    ) -> None:
        """Create a branch. Raises on error."""
        await self._request(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            installation_id,
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
        )

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
    ) -> None:
        """Create or update a file in a repo. Raises on error."""
        payload: dict = {
            "message": message,
            "content": content_b64,
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha
        await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            installation_id,
            json=payload,
        )

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
    ) -> dict:
        """Create a pull request. Returns response JSON. Raises on error."""
        resp = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            installation_id,
            json={"title": title, "body": body, "head": head, "base": base},
        )
        return resp.json()

    async def get_pull_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
    ) -> list[dict]:
        """Get files changed in a PR."""
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
            installation_id,
        )
        return resp.json()

    async def get_commits(
        self,
        owner: str,
        repo: str,
        installation_id: int,
        *,
        path: str = "",
        per_page: int = 30,
    ) -> list[dict]:
        """Get commits, optionally filtered by path."""
        params: dict[str, Any] = {"per_page": per_page}
        if path:
            params["path"] = path
        resp = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits",
            installation_id,
            params=params,
        )
        return resp.json()
