"""Event routing — thin dispatcher to registered tools."""

import logging

from .tools._registry import get_tools_for_event, get_tool_for_command

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

logger = logging.getLogger(__name__)


async def handle_webhook(event: str, data: dict) -> None:
    """Route webhook events to all matching registered tools."""
    action = data.get("action", "")

    tools = get_tools_for_event(event, action)
    if not tools:
        logger.debug("No tools matched event=%s action=%s", event, action)
        return

    for t in tools:
        logger.info("Running tool: %s (event=%s, action=%s)", t.name, event, action)
        try:
            await t.func(data)
        except Exception:
            logger.exception("Tool %s failed", t.name)
