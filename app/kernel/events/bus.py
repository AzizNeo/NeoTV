"""Subscription registry for outbox delivery.

The bus does **not** execute handlers inline and never swallows exceptions:
it only answers "who consumes event X?". Execution happens per (event,
consumer) pair in ``kernel.outbox.deliver`` so that one failing consumer is
retried and dead-lettered in isolation (see app.kernel.outbox.tasks).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

EventHandler = Callable[..., None]  # handler(event, *, uow) -> None


class DuplicateConsumerError(RuntimeError):
    pass


class UnknownConsumerError(LookupError):
    pass


class UnknownEventTypeError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class Subscription:
    event_name: str
    consumer: str
    handler: EventHandler
    queue: str = "outbox"
    owner: str = "kernel"


@dataclass
class EventBus:
    _subscriptions: dict[str, dict[str, Subscription]] = field(default_factory=dict)
    _consumers: dict[str, str] = field(default_factory=dict)

    def subscribe(self, subscription: Subscription) -> None:
        if subscription.consumer in self._consumers:
            raise DuplicateConsumerError(
                f"consumer '{subscription.consumer}' is already subscribed to "
                f"'{self._consumers[subscription.consumer]}'"
            )
        self._consumers[subscription.consumer] = subscription.event_name
        self._subscriptions.setdefault(subscription.event_name, {})[subscription.consumer] = subscription

    def consumers(self, event_name: str) -> list[Subscription]:
        return list(self._subscriptions.get(event_name, {}).values())

    def subscription(self, event_name: str, consumer: str) -> Subscription:
        try:
            return self._subscriptions[event_name][consumer]
        except KeyError:
            raise UnknownConsumerError(f"{event_name}/{consumer}") from None

    def describe(self) -> dict[str, list[str]]:
        return {name: sorted(subs) for name, subs in sorted(self._subscriptions.items())}

    def all(self) -> list[Any]:
        return [s for subs in self._subscriptions.values() for s in subs.values()]
