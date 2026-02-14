"""Pydantic models for code review results."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Severity(str, Enum):
    CRITICAL = "critical"
    MEDIUM = "medium"
    LOW = "low"


class ReviewComment(BaseModel):
    path: str
    line: int
    body: str


class ReviewResult(BaseModel):
    summary: str = ""
    comments: list[ReviewComment] = []
