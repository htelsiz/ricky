"""GitHub App authentication — JWT generation and installation token exchange."""

import os
import time
from pathlib import Path

import httpx
import jwt

GITHUB_API = "https://api.github.com"

_app_id: str | None = None
_private_key: bytes | None = None
_install_token: str | None = None
_install_token_expires: float = 0


def _get_app_id() -> str:
    global _app_id
    if _app_id is None:
        path = os.environ.get("APP_ID_FILE", "/secrets/app-id")
        _app_id = Path(path).read_text().strip()
    return _app_id


def _get_private_key() -> bytes:
    global _private_key
    if _private_key is None:
        path = os.environ.get("PRIVATE_KEY_FILE", "/secrets/private-key.pem")
        _private_key = Path(path).read_bytes()
    return _private_key


def _generate_jwt() -> str:
    """Generate a short-lived JWT for authenticating as the GitHub App."""
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": _get_app_id(),
    }
    return jwt.encode(payload, _get_private_key(), algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """Get an installation access token, caching until near expiry."""
    global _install_token, _install_token_expires

    if _install_token and time.time() < _install_token_expires:
        return _install_token

    app_jwt = _generate_jwt()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _install_token = data["token"]
    _install_token_expires = time.time() + 3300  # refresh 5 min before 1h expiry
    return _install_token


async def github_api(
    method: str,
    path: str,
    installation_id: int,
    accept: str = "application/vnd.github+json",
    **kwargs,
) -> httpx.Response:
    """Make an authenticated GitHub API request."""
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
