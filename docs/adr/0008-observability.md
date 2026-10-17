# ADR-0008 — Observability: correct metrics, one trace per request, SLOs and alerts as tested code

- Status: Accepted (2026-10)
- Area: `app/kernel/observability/`, `gunicorn.conf.py`, `deploy/prometheus/`, `deploy/grafana/`,
  `docs/runbooks.md`, `frontend/src/core/telemetry/`, `frontend/src/core/api/traceContext.js`

## Context

The platform had the beginnings — JSON logs with a request id, a Prometheus endpoint, an optional
OpenTelemetry hook — but none of it could be trusted in production:

- With gunicorn's two workers each process counted on its own and a scrape hit one at random:
  counters went backwards, latency saw half the traffic.
- Two gauges (`neotv_outbox_lag_seconds`, `neotv_outbox_dead_letters`) were declared and never
  set: they read 0 forever — a dashboard that says "fine" whatever happens.
- Tracing had never run: OpenTelemetry sat in an unlocked side file the image copied and never
  installed, so setting `OTEL_ENDPOINT` would have failed at boot.
- Nothing measured what viewers experience (time to first frame, stalls) or what browsers see,
  and there were no objectives, alerts, runbooks or dashboard.

## Decision

**Metrics are correct before they are many.**
- Prometheus multiprocess mode under gunicorn (`gunicorn.conf.py`: directory set in the master,
  emptied on start, dead workers' live gauges removed). Every gauge declares how it merges:
  `livemostrecent` for facts read from the database at scrape time, `livemax` for per-process
  state (circuit breakers, which each worker republishes after every request).
- State is read from its owner at scrape time (`best_effort`: a failing read never breaks the
  scrape). The kernel defines a metric; the module that owns the data feeds it (`post_boot`).
- Labels come from closed sets only (device, reason, source, vital name). Hosts, URLs, user ids
  and free text never become labels — cardinality and leakage, both.
- Viewer experience comes from the player's one QoE report per session, but only a *trusted* one
  is counted: the caller's own session, its first report, capped at the session's lifetime.
  Every report is still stored (contract unchanged).

**One trace per request, end to end.**
- OpenTelemetry, hash-locked in `requirements.txt`, off unless `OTEL_ENDPOINT` is set. Automatic
  spans for Flask, SQLAlchemy, `requests` (every egress call) and Celery; `endpoint()` handlers
  nest inside. Log lines carry `trace_id`/`span_id`.
- **OTLP over HTTP**, not gRPC: protobuf only (no `grpcio` in the image), passes ordinary proxies.
- **The server owns sampling.** A caller's trace id is continued (correlation) but its sampled
  flag is not obeyed — any browser could otherwise force 100 % tracing and flood the backend.
  Trace-id ratio sampling gives every service the same decision.
- The SPA starts the trace: every API call sends a W3C `traceparent` (flags `00`: "server
  decides"); `ApiError.traceId` joins a failed call to its backend trace and logs. No OTel JS SDK
  (bundle size, CSP).

**Browsers are first-class.** Web Vitals and uncaught errors go to our own endpoint
(`POST /api/v1/kernel/client-events`) with `sendBeacon` — no third-party service, CSP untouched.
Public endpoint, hostile input assumed: closed label sets, strict schema, ≤ 20 events, per-IP
rate limit, and messages/stacks/paths scrubbed of query strings and JWT-shaped tokens before
they are logged. The reporter never floods (each distinct error once, ≤ 10 per page).

**Objectives and alerts are code, tested like code.**
- SLOs: API availability 99.5 % (no 5xx), API latency 99 % ≤ 1 s, playback start 95 % ≤ 3 s.
  Probes, telemetry and the media proxy are outside the API SLIs (the proxy's errors are mostly
  the origin's; it has its own alert).
- Multi-window, multi-burn-rate alerts (Google SRE Workbook): page at 14.4× over 1 h **and** 5 m,
  ticket at 6× over 6 h **and** 30 m — no pages for blips, a page within minutes for real burns.
- Rules and the Grafana dashboard are *generated* from short Python sources (reviewable), and CI
  keeps the generated files in sync. `promtool test rules` proves behaviour on synthetic series
  (an outage pages, a healthy system stays quiet, a slow leak tickets but never pages, the proxy
  never counts against the API); every dashboard query is parsed by promtool and checked against
  the series that actually exist — and every exported metric must appear on a panel.
- Every alert links to a runbook section, and a test keeps alerts and runbooks one-to-one.

## Alternatives not taken

- **A SaaS (Datadog, Sentry, New Relic)** for browser errors and APM: fastest to start, but a
  third-party script in the page (CSP exception, privacy) and vendor lock-in for a project meant
  to show the mechanics. The OTLP/Prometheus choice keeps every vendor possible later.
- **OTLP/gRPC**: the default in many SDKs, rejected for image size and proxy friction.
- **Obeying the caller's sampling flag** (`ParentBased` defaults): convenient, unsafe for a public API.
- **Threshold alerts on raw error rates**: simpler, but they page on blips and miss slow leaks.

## Consequences

- Production needs `METRICS_TOKEN` once Prometheus runs in its own container; the token is read
  from a mounted file (`deploy/prometheus/prometheus.yml`), never from git.
- Tests that touch process-wide state (prometheus_client's storage mode, OpenTelemetry's
  instrumentors) run in subprocesses or clean up through `uninstall_tracing()`.
- A new metric must be put on the dashboard and a new alert must get a runbook section, or CI
  fails — deliberately: an unwatched metric and an alert without instructions are both debt.
- Known follow-up: a `flask kernel dead-letters list|replay|resolve` command would replace the
  runbook's shell-and-SQL procedure.
