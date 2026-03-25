from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from syndicateclaw.models import AuditEvent, AuditEventType

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


class EventBus:
    """Simple in-process async event bus (singleton).

    Subscribers are notified concurrently when an event is published.
    Can be swapped for a Redis/Kafka-backed implementation later.
    """

    _instance: EventBus | None = None
    _subscribers: dict[str, list[Callable[..., Any]]]
    _lock: asyncio.Lock

    def __new__(cls) -> EventBus:
        if cls._instance is None:
            inst = super().__new__(cls)
            inst._subscribers = {}
            inst._lock = asyncio.Lock()
            cls._instance = inst
        return cls._instance

    # -- public API ----------------------------------------------------------

    def subscribe(self, event_type: str | AuditEventType, handler: Callable[..., Any]) -> None:
        key = event_type.value if isinstance(event_type, AuditEventType) else event_type
        self._subscribers.setdefault(key, []).append(handler)
        logger.debug("event_bus_subscribed", event_type=key, handler=handler.__qualname__)

    def unsubscribe(self, event_type: str, handler: Callable[..., Any]) -> None:
        key = event_type.value if isinstance(event_type, AuditEventType) else event_type
        handlers = self._subscribers.get(key, [])
        try:
            handlers.remove(handler)
            logger.debug("event_bus_unsubscribed", event_type=key, handler=handler.__qualname__)
        except ValueError:
            logger.warning(
                "event_bus_unsubscribe_miss", event_type=key, handler=handler.__qualname__
            )

    async def publish(self, event: AuditEvent) -> None:
        """Notify all subscribers for the event type."""
        key = event.event_type.value
        handlers = self._subscribers.get(key, [])
        if not handlers:
            return

        results = await asyncio.gather(
            *(self._invoke(h, event) for h in handlers),
            return_exceptions=True,
        )
        for idx, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(
                    "event_bus_handler_error",
                    event_type=key,
                    handler=handlers[idx].__qualname__,
                    error=str(result),
                )

    async def publish_and_persist(self, event: AuditEvent, audit_service: Any) -> AuditEvent:
        """Persist the event to the database then notify subscribers."""
        persisted: AuditEvent = await audit_service.create(event)
        await self.publish(persisted)
        return persisted

    # -- internals -----------------------------------------------------------

    @staticmethod
    async def _invoke(handler: Callable[..., Any], event: AuditEvent) -> None:
        result = handler(event)
        if asyncio.iscoroutine(result):
            await result

    @classmethod
    def reset(cls) -> None:
        """Tear down the singleton — useful in tests."""
        cls._instance = None
