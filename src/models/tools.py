"""Pydantic models for tool-specific responses."""

from __future__ import annotations

from pydantic import BaseModel


class SizeGuardResult(BaseModel):
    lines_added: int = 0
    lines_removed: int = 0
    files_changed: int = 0
    passed: bool = True
    message: str = ""


class TodoItem(BaseModel):
    path: str
    line: int
    text: str
    tag: str = "TODO"  # TODO, FIXME, HACK, XXX


class CIFailureReport(BaseModel):
    run_id: int
    conclusion: str = ""
    diagnosis: str = ""
    suggested_fix: str = ""
