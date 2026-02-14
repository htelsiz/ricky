"""Tool registry — decorator-based dispatch for webhook event handlers."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

ToolFunc = Callable[..., Awaitable[None]]


@dataclass
class ToolDef:
    """A registered tool with its trigger conditions."""

    name: str
    func: ToolFunc
    events: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)  # e.g. ["@ricky fix"]


_tools: list[ToolDef] = []


def tool(
    name: str,
    *,
    events: list[str] | None = None,
    actions: list[str] | None = None,
    commands: list[str] | None = None,
):
    """Register a tool function for webhook dispatch.

    Usage:
        @tool("size_guard", events=["pull_request"], actions=["opened", "synchronize", "reopened"])
        async def size_guard(ctx: ToolContext) -> None:
            ...
    """
    def decorator(func: ToolFunc) -> ToolFunc:
        _tools.append(ToolDef(
            name=name,
            func=func,
            events=events or [],
            actions=actions or [],
            commands=commands or [],
        ))
        return func
    return decorator


def get_tools_for_event(event: str, action: str) -> list[ToolDef]:
    """Return all tools that should run for a given event/action pair."""
    matched = []
    for t in _tools:
        if event in t.events:
            if not t.actions or action in t.actions:
                matched.append(t)
    return matched


def get_tool_for_command(command: str) -> ToolDef | None:
    """Find a tool matching an @ricky command string."""
    cmd_lower = command.lower().strip()
    for t in _tools:
        for c in t.commands:
            if c in cmd_lower:
                return t
    return None


def all_tools() -> list[ToolDef]:
    """Return all registered tools."""
    return list(_tools)
