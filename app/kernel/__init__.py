"""NeoTV kernel.

The kernel is the *board* the puzzle pieces (modules) are placed on. It owns
cross-cutting infrastructure only — configuration, dependency injection, the
module registry, persistence primitives, the event/outbox pipeline, the HTTP
contract, security primitives, resilience and observability.

Hard rule: the kernel never imports ``app.modules``. Modules depend on the
kernel, never the other way round (enforced by import-linter, see
``.importlinter``).
"""
