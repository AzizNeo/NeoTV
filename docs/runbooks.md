# Runbooks

What to do when an alert from `deploy/prometheus/neotv.rules.yml` fires. Each alert links here
(`runbook_url`); a test keeps every alert and every section in step.

Conventions: commands assume the production stack (`docker-compose.yml`: services `api`,
`worker-default`, `worker-playlist`, `worker-transcode`, `beat`, `web`, `postgres`, `redis`).
Logs are JSON — filter by `logger`, `request_id` or `trace_id` (a log line's `trace_id` opens the
request's trace in the tracing backend when `OTEL_ENDPOINT` is set). **Severity:** `page` = act
now; `ticket` = act within working hours.

**Error budgets in one paragraph.** An SLO of 99.5 % allows 0.5 % bad events over 30 days — the
budget. A *burn rate* of 14.4 spends 2 % of the month's budget in one hour; at that pace the month
is gone in two days, so it pages. A burn of 6 over six hours is a slow leak: a ticket. When the
budget is spent, reliability work comes before new features until it recovers.

---

<a id="slo-availability"></a>
## SLO: API availability (99.5 % of requests without a 5xx)

**Means:** server errors on the API (probes, telemetry and the media proxy excluded).

**Check**
1. Which endpoints: `sum by (endpoint, status) (rate(neotv_http_requests_total{status=~"5.."}[5m]))`.
2. The errors themselves: `docker compose logs --since 15m api | grep '"level": "ERROR"'` — each
   line carries `request_id` (and `trace_id`).
3. Dependencies: `curl -s localhost:8000/api/v1/health/ready` from the API container (database,
   migrations, Redis), and `NeoTVCircuitOpen`.

**Likely causes:** database or Redis unavailable or saturated; a deploy with a failing migration;
one endpoint broken by a release.

**Fix:** a release → roll back the image tag. A dependency → restore it; the API recovers on its
own (circuit breakers close after their recovery window). One endpoint → disable its module
(`DISABLED_MODULES`) if it is optional, rather than leaving errors on.

**Escalate** if the error ratio does not fall within 15 minutes of the fix.

<a id="slo-latency"></a>
## SLO: API latency (99 % of requests within 1 s)

**Means:** requests are answered, but slowly.

**Check**
1. Slow endpoints: `histogram_quantile(0.99, sum by (endpoint, le) (rate(neotv_http_request_seconds_bucket[5m])))`.
2. A slow request's trace (by `trace_id` from its log line): which span takes the time — SQL,
   an outbound call (TMDB, a playlist host), or the handler.
3. Database: active connections and long queries (`pg_stat_activity`).

**Likely causes:** a missing index after a data change; an outbound dependency slow but not yet
failing (no circuit trip); CPU saturation (`--workers` / `--threads` too low for the traffic).

**Fix:** add the index / cache the call / scale the API (`docker compose up -d --scale api=N`
behind the edge). Do not raise timeouts to make the alert go away.

<a id="slo-playback-start"></a>
## SLO: playback start (95 % of streams show a first frame within 3 s)

**Means:** viewers wait too long after pressing play (from the players' QoE reports).

**Check**
1. Which devices: `histogram_quantile(0.95, sum by (device, le) (rate(neotv_playback_startup_seconds_bucket[30m])))`.
2. Origin health: `NeoTVOriginFailures` and `sum by (reason) (rate(neotv_playback_proxy_errors_total[10m]))`.
3. Proxy latency: the `playback.proxy` endpoint in `neotv_http_request_seconds`.

**Likely causes:** a slow or distant origin; the media proxy's host saturated (network); a release
that delays the player's first request.

**Fix:** move the affected channels to `direct` delivery if their CDN is public and fast; add API
capacity for the proxy; roll back a front-end release that changed the player start path.

---

<a id="api-down"></a>
## NeoTVApiDown — Prometheus cannot scrape the API (page)

**Check:** `docker compose ps api` (state, restarts) · `docker compose logs --tail 100 api` ·
from the Prometheus host, `curl -s http://api:8000/api/v1/health/live`.

**Likely causes:** the container crash-loops (a boot error names its cause in the last log lines:
missing setting, unreachable database, a migration not applied); the host is out of memory; the
scrape token (`METRICS_TOKEN`) changed on one side only.

**Fix:** address the named boot error and `docker compose up -d api`. A failed migration:
`docker compose run --rm migrate` and read its output before starting the API again.

<a id="outbox-lagging"></a>
## NeoTVOutboxLagging — domain events wait over 5 minutes (ticket)

**Means:** effects of user actions (e-mails, playback bookkeeping, plan changes) are delayed.

**Check:** workers alive — `docker compose ps worker-default beat` and
`docker compose exec worker-default celery -A app.wsgi:celery inspect ping`; retries in progress —
`docker compose logs --since 30m worker-default | grep outbox.retry`.

**Likely causes:** `beat` stopped (nothing dispatches); `worker-default` down or saturated; one
consumer failing and retrying (back-off up to 10 minutes).

**Fix:** restart the stopped service; a failing consumer → see its error in the retry lines and
fix it. Nothing is lost while lagging: events wait in `kernel_outbox`.

<a id="dead-letters"></a>
## NeoTVDeadLetters — deliveries gave up after their retries (ticket)

**Means:** an event could not be applied by one consumer after every retry. The event and the
error are kept in `kernel_dead_letters`; nothing was silently dropped.

**Check**
```sql
SELECT d.id, d.event_id, d.consumer, d.failed_at, left(d.error, 300) AS error, o.event_name
FROM kernel_dead_letters d LEFT JOIN kernel_outbox o ON o.id = d.event_id
WHERE d.resolved_at IS NULL ORDER BY d.failed_at;
```

**Fix:** correct the cause (the `error` column names it), then redeliver — delivery is idempotent
(the inbox makes a second application a no-op), so replaying is safe:

```bash
docker compose exec api flask --app app.wsgi shell
>>> from app.kernel.outbox.tasks import deliver_event
>>> deliver_event.delay("<event_id>", "<consumer>")
```

Then mark it handled: `UPDATE kernel_dead_letters SET resolved_at = now() WHERE id = <id>;`.
Replay before the purge removes old dispatched events (the task then answers `missing`).

<a id="circuit-open"></a>
## NeoTVCircuitOpen — a dependency is failing and calls to it are short-circuited (ticket)

**Means:** after repeated failures the breaker named in the alert stops calling that dependency
for its recovery window, then probes it again. Features using it degrade by design.

**Check:** the dependency named by `name` (e.g. `tmdb` → TMDB status page; an egress breaker →
the remote host); logs for the failures that opened it.

**Fix:** usually nothing on our side — the breaker closes by itself once a probe succeeds. If the
dependency is ours, restore it. If the circuit flaps, its thresholds are too tight: tune them in
code, with a test.

<a id="origin-failures"></a>
## NeoTVOriginFailures — over 5 % of media requests fail at the origin (ticket)

**Means:** the channels' source servers do not answer the media proxy properly.

**Check:** causes — `sum by (reason) (rate(neotv_playback_proxy_errors_total[10m]))`; hosts —
`docker compose logs --since 30m api | grep 'proxy upstream'` (hosts are logged, never labelled).

| reason | usually |
| --- | --- |
| `dns`, `connect`, `timeout`, `tls` | the origin is down or unreachable from our network |
| `blocked` | the egress rules refuse the host (private address, disallowed port) — as designed |
| `http_4xx` | the source URL moved or its token expired: update the channel |
| `http_5xx` | the origin's own outage |
| `not_a_playlist` | the source now answers HTML (a login or error page) |

**Fix:** update or disable the affected channels in Admin → Catalogue / Live; re-sync an
imported playlist.

<a id="browser-errors"></a>
## NeoTVBrowserErrors — viewers' browsers report uncaught errors (ticket)

**Means:** the SPA throws in real browsers (more than 5 per minute for 15 minutes).

**Check:** `docker compose logs --since 1h api | grep '"logger": "client"'` — each line has
`client_message`, `client_stack`, `client_path`, `client_release` and, for failed API calls,
`client_trace_id` (that call's backend trace and logs). Group by `client_release`: errors that
start with one release point at it.

**Fix:** roll back the front-end release (the `web` image) if a release introduced them; fix
forward otherwise. Messages, stacks and paths are scrubbed of query strings and tokens before
they are logged.

<a id="xtream-guessing"></a>
## NeoTVXtreamGuessing — addresses keep sending wrong TV app credentials (ticket)

**Means:** addresses that failed 30 TV-app credential checks within 10 minutes keep calling
(`XtreamAuthGuard`, ADR-0011): more than one refused request per minute for 10 minutes. Their
requests are refused without checking credentials, so this is load and intent, not a breach — app
passwords are random and no account is locked by it.

**Check:** `sum by (result) (rate(neotv_xtream_auth_total[10m]))` — `denied` rising with
`blocked` is guessing; `denied` alone at a low rate is usually one TV with a revoked or changed
credential. The addresses are in the access log (`docker compose logs --since 1h web | grep
'/player_api.php\|/live/'`); credentials there are masked by design.

**Fix:** if one or a few addresses: block them at the edge (firewall / load balancer). If it is
spread: the per-address guard keeps each to ~30 tries per 10 minutes; raise nothing, watch the
`denied` rate. If an owner reports their TV stopped after a password change, that is expected —
a new account password revokes every app credential; they create a new one under Account →
TV apps.
