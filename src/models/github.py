"""Pydantic models for GitHub API objects."""

from __future__ import annotations

from pydantic import BaseModel


class PullRequest(BaseModel):
    number: int
    title: str
    body: str | None = ""
    head_sha: str
    head_ref: str
    base_ref: str


class Repository(BaseModel):
    owner: str
    name: str


class CheckRunOutput(BaseModel):
    title: str
    summary: str
    text: str = ""


class Label(BaseModel):
    name: str
    color: str = ""
    description: str = ""
