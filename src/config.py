"""Centralized configuration — Pydantic BaseSettings with env var bindings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class SecretsSettings(BaseSettings):
    """Paths to secret files mounted into the container."""

    webhook_secret_file: str = Field("/secrets/webhook-secret", alias="WEBHOOK_SECRET_FILE")
    app_id_file: str = Field("/secrets/app-id", alias="APP_ID_FILE")
    private_key_file: str = Field("/secrets/private-key.pem", alias="PRIVATE_KEY_FILE")
    gcp_sa_key_file: str = Field("/secrets/gcp-service-account.json", alias="GCP_SA_KEY_FILE")
    gcp_project_file: str = Field("/secrets/gcp-project", alias="GCP_PROJECT_FILE")

    def read(self, path: str) -> str:
        """Read and strip a secret file."""
        return Path(path).read_text().strip()


class GeminiSettings(BaseSettings):
    """Vertex AI / Gemini configuration."""

    gcp_project: str = Field("", alias="GCP_PROJECT")
    gcp_location: str = Field("us-central1", alias="GCP_LOCATION")
    model: str = Field("gemini-3-pro-preview", alias="GEMINI_MODEL")
    temperature: float = 0.7
    max_output_tokens: int = 8192
    timeout: float = 120.0


class RickySettings(BaseSettings):
    """Ricky-specific tool configuration."""

    max_pr_lines: int = Field(500, alias="RICKY_MAX_PR_LINES")
    max_pr_files: int = Field(15, alias="RICKY_MAX_PR_FILES")
    auto_fix_enabled: bool = Field(False, alias="RICKY_AUTO_FIX_ENABLED")
    todo_create_issues: bool = Field(True, alias="RICKY_TODO_CREATE_ISSUES")


class Settings(BaseSettings):
    """Top-level settings container."""

    secrets: SecretsSettings = SecretsSettings()
    gemini: GeminiSettings = GeminiSettings()
    ricky: RickySettings = RickySettings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
