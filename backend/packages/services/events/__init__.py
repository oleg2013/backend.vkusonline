"""In-process event dispatcher — simple observer pattern for triggering side effects."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Coroutine

import structlog

logger = structlog.get_logger(__name__)

# Handler type: async callable accepting a dict
EventHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventDispatcher:
    """Dispatches events to registered async handlers.

    Usage:
        dispatcher = EventDispatcher()
        dispatcher.subscribe("order_status_changed", my_handler)
        await dispatcher.dispatch("order_status_changed", {"order": order, ...})
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)
        logger.debug("event_handler_subscribed", event_type=event_type, handler=handler.__name__)

    async def dispatch(self, event_type: str, data: dict[str, Any]) -> None:
        handlers = self._handlers.get(event_type, [])
        if not handlers:
            logger.debug("no_handlers_for_event", event_type=event_type)
            return

        for handler in handlers:
            try:
                await handler(data)
            except Exception as exc:
                logger.error(
                    "event_handler_error",
                    event_type=event_type,
                    handler=handler.__name__,
                    error=str(exc),
                )


# Global singleton — initialized during app startup
event_dispatcher = EventDispatcher()
