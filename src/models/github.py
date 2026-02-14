"""Pydantic models for GitHub webhook payloads and API objects.

Each model uses ``model_validator(mode="before")`` to flatten the nested
JSON GitHub sends into the flat fields tools actually need.  No manual
``.get()`` chains anywhere else in the codebase.
"""

from typing import Any

from pydantic import BaseModel, model_validator


class Repository(BaseModel):
    owner: str = ""
    name: str = ""
    full_name: str = ""
    default_branch: str = "main"

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("owner"), dict):
            data = {**data, "owner": data["owner"].get("login", "")}
        return data


class PullRequest(BaseModel):
    number: int
    title: str = ""
    body: str = ""
    head_sha: str = ""
    head_ref: str = ""
    base_ref: str = ""
    mergeable: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if isinstance(data, dict):
            head = data.get("head") or {}
            base = data.get("base") or {}
            return {
                **data,
                "body": data.get("body") or "",
                "head_sha": head.get("sha", ""),
                "head_ref": head.get("ref", ""),
                "base_ref": base.get("ref", ""),
            }
        return data


class Comment(BaseModel):
    id: int = 0
    body: str = ""
    user: str = ""

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("user"), dict):
            data = {**data, "user": data["user"].get("login", "")}
        return data


class Issue(BaseModel):
    number: int
    title: str = ""
    has_pull_request: bool = False

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if isinstance(data, dict):
            return {**data, "has_pull_request": "pull_request" in data}
        return data


class CheckSuite(BaseModel):
    id: int = 0
    head_sha: str = ""
    conclusion: str = ""
    pr_numbers: list[int] = []

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if isinstance(data, dict):
            prs = data.get("pull_requests") or []
            return {
                **data,
                "pr_numbers": [p["number"] for p in prs if "number" in p],
            }
        return data


class CheckRun(BaseModel):
    id: int = 0
    name: str = ""
    head_sha: str = ""
    conclusion: str = ""
    pr_numbers: list[int] = []
    output_summary: str = ""
    output_text: str = ""

    @model_validator(mode="before")
    @classmethod
    def _flatten(cls, data: Any) -> Any:
        if isinstance(data, dict):
            prs = data.get("pull_requests") or []
            output = data.get("output") or {}
            return {
                **data,
                "pr_numbers": [p["number"] for p in prs if "number" in p],
                "output_summary": output.get("summary") or "",
                "output_text": output.get("text") or "",
            }
        return data


class CheckRunOutput(BaseModel):
    """Payload for creating a check run."""

    title: str
    summary: str
    text: str = ""


class Label(BaseModel):
    name: str
    color: str = ""
    description: str = ""


class WebhookContext(BaseModel):
    """Parsed webhook payload — the single arg every tool receives."""

    event: str
    action: str
    installation_id: int
    repo: Repository
    pr: PullRequest | None = None
    comment: Comment | None = None
    issue: Issue | None = None
    check_suite: CheckSuite | None = None
    check_run: CheckRun | None = None

    @classmethod
    def from_webhook(cls, event: str, data: dict) -> "WebhookContext":
        """Build a context by letting each sub-model validate itself."""
        return cls.model_validate({
            "event": event,
            "action": data.get("action", ""),
            "installation_id": (data.get("installation") or {}).get("id", 0),
            "repo": data.get("repository") or {},
            "pr": data.get("pull_request"),
            "comment": data.get("comment"),
            "issue": data.get("issue"),
            "check_suite": data.get("check_suite"),
            "check_run": data.get("check_run"),
        })
