"""Outbox health as metrics, read at scrape time from the database (the one source of truth).

* ``neotv_outbox_lag_seconds`` — age of the oldest event not yet delivered. Grows when workers
  are down or a consumer keeps failing; 0 when everything is delivered.
* ``neotv_outbox_dead_letters`` — deliveries that gave up and wait for a human.

Both were declared before but never set, so they read 0 forever — a dashboard that says
"all is well" whatever happens. A failed read (database down) leaves the previous values and
never breaks the scrape: losing visibility exactly when the system is in trouble is worse.
"""

from __future__ import annotations

from app.kernel.observability.metrics import Metrics
from app.kernel.outbox.repository import DeadLetterRepository, OutboxRepository
from app.kernel.resilience.best_effort import best_effort
from app.kernel.time import Clock
from app.kernel.uow import UnitOfWorkFactory


def install_outbox_metrics(metrics: Metrics, uow: UnitOfWorkFactory, clock: Clock) -> None:
    def read() -> None:
        with uow() as unit:
            oldest = OutboxRepository(unit.session).oldest_undelivered_at()
            dead = DeadLetterRepository(unit.session).open_count()
        metrics.outbox_lag.set(max(0.0, (clock.now() - oldest).total_seconds()) if oldest else 0.0)
        metrics.dead_letters.set(dead)

    metrics.add_collector(lambda: best_effort(read, op="metrics.outbox"))
