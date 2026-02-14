"""GitHub App authentication — delegates to _base_auth.

Kept for backward compatibility; new code should import from _base_auth or clients.github.
"""

from ._base_auth import get_installation_token, GITHUB_API  # noqa: F401
import httpx


async def github_api(
    method: str,
    path: str,
    installation_id: int,
    accept: str = "application/vnd.github+json",
    **kwargs,
) -> httpx.Response:
    """Make an authenticated GitHub API request (legacy helper)."""
    token = await get_installation_token(installation_id)
    async with httpx.AsyncClient() as client:
        resp = await client.request(
            method,
            f"{GITHUB_API}{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": accept,
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=30.0,
            **kwargs,
        )
    return resp
