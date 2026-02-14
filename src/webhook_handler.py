"""Event routing — thin dispatcher to registered tools."""

import logging

from .models.github import WebhookContext
from .tools._registry import get_tools_for_event

# Import tool modules so they register via @tool decorator
from .tools import review  # noqa: F401
from .tools import size_guard  # noqa: F401
from .tools import todo_tracker  # noqa: F401
from .tools import ci_reporter  # noqa: F401
from .tools import auto_fix  # noqa: F401
from .tools import test_coverage  # noqa: F401
from .tools import dead_code  # noqa: F401
from .tools import benchmark  # noqa: F401
from .tools import blame  # noqa: F401
from .tools import breaking  # noqa: F401
from .tools import dep_update  # noqa: F401
from .tools import conflict  # noqa: F401

log = logging.getLogger(__name__)


async def handle_webhook(event: str, data: dict) -> None:
    """Route webhook events to all matching registered tools."""
    ctx = WebhookContext.from_webhook(event, data)

    tools = get_tools_for_event(ctx.event, ctx.action)
    if not tools:
        log.debug("No tools matched event=%s action=%s", ctx.event, ctx.action)
        return

    for t in tools:
        log.info("Running tool: %s (event=%s, action=%s)", t.name, ctx.event, ctx.action)
        try:
            await t.func(ctx)
        except Exception:
            log.exception("Tool %s failed", t.name)
