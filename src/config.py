"""Centralized configuration via Pydantic BaseSettings.

Each service has its own settings class with an env_prefix.
Settings are only loaded when the specific service is used via ``from_env()``.
"""

from pydantic_settings import BaseSettings


class GithubSettings(BaseSettings):
    """GitHub App authentication paths."""

    app_id_file: str = "/secrets/app-id"
    private_key_file: str = "/secrets/private-key.pem"
    webhook_secret_file: str = "/secrets/webhook-secret"

    model_config = {"env_prefix": "GITHUB_"}


class GcpSettings(BaseSettings):
    """GCP project and credentials."""

    project: str = ""
    location: str = "us-central1"
    sa_key_file: str = "/secrets/gcp-service-account.json"
    project_file: str = "/secrets/gcp-project"

    model_config = {"env_prefix": "GCP_"}


class GeminiSettings(BaseSettings):
    """Gemini model parameters."""

    model: str = "gemini-3-pro-preview"
    temperature: float = 0.7
    max_output_tokens: int = 8192
    timeout: float = 120.0

    model_config = {"env_prefix": "GEMINI_"}


class RickySettings(BaseSettings):
    """Application-level settings."""

    max_pr_lines: int = 500
    max_pr_files: int = 15
    auto_fix_enabled: bool = False
    auto_fix_max_files: int = 10
    todo_create_issues: bool = True

    model_config = {"env_prefix": "RICKY_"}
