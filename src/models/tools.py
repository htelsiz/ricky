"""Pydantic models for tool-specific responses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SizeGuardResult(BaseModel):
    lines_added: int = 0
    lines_removed: int = 0
    files_changed: int = 0
    passed: bool = True
    message: str = ""


class TodoItem(BaseModel):
    file: str
    line: int
    kind: Literal["TODO", "FIXME", "HACK", "NOTE"]
    title: str = Field(
        max_length=72,
        description=(
            "Imperative summary, max 72 characters, no trailing punctuation, "
            "do not include the file name."
        ),
    )
    context: str = Field(
        description=(
            "One or two sentences explaining what needs to be done, grounded "
            "in the surrounding code."
        ),
    )


class TodoResponse(BaseModel):
    todos: list[TodoItem]


class CIFailureReport(BaseModel):
    run_id: int
    conclusion: str = ""
    diagnosis: str = ""
    suggested_fix: str = ""
