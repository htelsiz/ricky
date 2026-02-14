"""Base HTTP client for Ricky (httpx-based)."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class BaseClient:
    """Thin httpx wrapper with auth header injection."""

    def __init__(self, base_url: str, *, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _headers(self, token: str, accept: str = "application/vnd.github+json") -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        accept: str = "application/vnd.github+json",
        **kwargs,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.request(
                method,
                url,
                headers=self._headers(token, accept),
                timeout=self._timeout,
                **kwargs,
            )
        return resp
