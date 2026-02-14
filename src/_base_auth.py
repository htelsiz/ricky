"""GitHub App authentication — JWT generation and installation token exchange.

Extracted as a standalone module so both clients/github.py and legacy code can import it.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
import jwt

from .config import get_settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

_app_id: str | None = None
_private_key: bytes | None = None
_install_tokens: dict[int, tuple[str, float]] = {}


def _get_app_id() -> str:
    global _app_id
    if _app_id is None:
        _app_id = get_settings().secrets.read(get_settings().secrets.app_id_file)
    return _app_id


def _get_private_key() -> bytes:
    global _private_key
    if _private_key is None:
        path = get_settings().secrets.private_key_file
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
    cached = _install_tokens.get(installation_id)
    if cached and time.time() < cached[1]:
        return cached[0]

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

    token = data["token"]
    expires = time.time() + 3300  # refresh 5 min before 1h expiry
    _install_tokens[installation_id] = (token, expires)
    return token
