# ADR-0009 — Load testing: real client pacing, SLO thresholds, limits left on

- Status: Accepted (2026-10)
- Area: `deploy/load/neotv.js`, `tools/load_seed.py`, `tools/k6_summary.py`,
  `.github/workflows/ci.yml` (demo job), `.github/workflows/load.yml`

## Context

ADR-0008 made the system observable and set objectives. Nothing yet showed that those objectives
hold under concurrency, or warned when a change makes the system slower: correctness tests run
one request at a time.

## Decision

**k6**, scripted in JavaScript, a single static binary (pinned version, SHA256 checked in CI). It
models open and closed workloads (arrival rate and virtual users), tags requests, and fails a run
on thresholds — what a regression gate needs. Alternatives below.

**The scenario is what clients actually do.** A viewer: home rails → browse → a title → channels →
opens a stream → a heartbeat every 10 s (the player's interval) → QoE report → release. Alongside, a
steady stream of sign-ins, because password hashing is the most CPU-hungry request. Each viewer
has its own account and device id, as in reality (one stream per account; a device replaces its
own slot).

**Thresholds are the production SLOs, not numbers chosen for the test**: server errors < 0.5 %,
p99 ≤ 1 s, on the same requests the SLIs count. Setup's warm-up (cold workers, first sign-ins) is
tagged apart and does not count — Prometheus never sees a boot in isolation either.

**Rate limits stay on.** Turning them off would measure a system nobody runs, and a bypass in
production code is an attack surface. The test is paced under the limits instead, and **any 429
fails the run**: it means the test's pacing is wrong. Consequences of one shared source IP are
checked before a run starts (see below).

**Accounts are seeded, not registered.** Registration is limited per IP (as it must be), so
`tools/load_seed.py` creates `load-NNNN` accounts through the identity service — idempotent and
refused in production, where accounts with a shared known password would be a hole.

**Media is not fetched.** The demo's sources are third parties' public streams; a load test must
not load someone else's servers. Opening, keeping and releasing streams is measured; the media
proxy's throughput needs a local origin and is a separate test.

**Two levels.**
- Every push: CI's demo job runs the `smoke` profile through nginx against the full Docker stack
  (Postgres, Redis, gunicorn). A regression gate — shared runners are too noisy for capacity.
- On demand: the *Load test* workflow runs the `load` profile (ramp to N viewers, hold, ramp
  down) and reports thresholds, per-endpoint latency and containers' CPU and memory.

**The k6 summary export never leaves the runner**: its `setup_data` holds the accounts' access
tokens. Only the Markdown made from its `metrics` is published.

## Alternatives not taken

- **Locust** (Python): the team's language, but workers per core for real load and no built-in
  pass/fail thresholds.
- **JMeter / Gatling**: JVM, heavier to install and to review in a pull request.
- **wrk / hey**: one URL at a time; no sessions, no flows.
- **Disabling rate limits during tests** (an environment flag): rejected above.

## Consequences

- A change that adds latency or errors under concurrency fails CI.
- A new endpoint in the scenario must be named in `ENDPOINTS`, or the script stops with its name.
- `playback.release` is limited to 5/s per IP. From one IP that bounds the test (viewers ≤
  4 × (watch seconds + 10), validated before a run); in production it can bound viewers behind one
  carrier-grade NAT. Nothing is lost when it bites — an unreleased slot frees itself 35 s after the
  last heartbeat — to be reviewed against the capacity results and real traffic.

## Results

Capacity runs (the *Load test* workflow) are recorded here as they are made.

**2026-10-17 — 50 viewers, 40 s per view** (GitHub runner, 2 vCPU; whole stack on the same machine
as k6: Postgres, Redis, 2 gunicorn workers × threads, worker, beat, nginx). 1 min ramp, 3 min hold.

| | |
| --- | --- |
| Result | all thresholds passed; 0 errors, 0 rate-limited, 100 % checks |
| Traffic | 2,905 requests (8.7/s), 523 viewer sessions, 52 virtual users at peak |
| API p99 (SLO ≤ 1 s) | **81 ms** |

| Endpoint | Requests | median | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `auth.login` | 321 | 63 ms | 92 ms | 124 ms | 172 ms |
| `titles.rails` | 259 | 28 ms | 46 ms | 71 ms | 117 ms |
| `titles.browse` | 259 | 11 ms | 20 ms | 40 ms | 98 ms |
| `titles.detail` | 259 | 9.1 ms | 18 ms | 23 ms | 29 ms |
| `catalog.list` | 260 | 6.5 ms | 13 ms | 21 ms | 22 ms |
| `playback.open` | 259 | 10 ms | 20 ms | 33 ms | 36 ms |
| `playback.heartbeat` | 777 | 5.3 ms | 9.6 ms | 16 ms | 34 ms |
| `playback.qoe` | 255 | 5.7 ms | 11 ms | 17 ms | 20 ms |
| `playback.release` | 255 | 4.7 ms | 10 ms | 15 ms | 37 ms |

Reading it:
- **50 concurrent viewers use about 8 % of the latency budget** (p99 81 ms of 1 s). This run says
  the expected peak is comfortable; it does not say where the limit is — that needs a breakpoint
  run (more viewers until a threshold breaks).
- **Sign-in is the most expensive request** (median 63 ms, password hashing — deliberate), then
  the home rails (several queries per call). Both are the first candidates when capacity matters.
- Container CPU and memory were sampled *after* the run in this report (idle values, not shown);
  the workflow now samples every 10 s during the run and reports peaks.

**2026-10-17 — 200 viewers, 40 s per view** (same runner and stack; container peaks sampled every 10 s).

| | |
| --- | --- |
| Result | **failed on `rate_limited`: 9 requests got 429**; the SLO thresholds held |
| Errors (SLO < 0.5 %) | 0.09 % — the nine 429s; no server errors |
| API p99 (SLO ≤ 1 s) | **357 ms** (×4.4 from 50 viewers) |
| Traffic | 10,759 requests (24.4/s), 1,269 viewer sessions, 202 virtual users at peak |
| Container peaks | api 122 % CPU (of 200 %), worker 86 %, postgres 39 %, beat 32 %, redis 8 %; memory ≤ 220 MiB each |

| Endpoint | Requests | median | p95 | p99 | max |
| --- | ---: | ---: | ---: | ---: | ---: |
| `titles.rails` | 1,032 | 59 ms | 345 ms | 700 ms | 1,174 ms |
| `auth.login` | 471 | 108 ms | 395 ms | 599 ms | 1,000 ms |
| `playback.open` | 1,032 | 24 ms | 175 ms | 329 ms | 746 ms |
| `titles.browse` | 1,032 | 23 ms | 154 ms | 324 ms | 1,135 ms |
| `titles.detail` | 1,032 | 18 ms | 123 ms | 268 ms | 462 ms |
| `catalog.list` | 1,033 | 12 ms | 98 ms | 222 ms | 558 ms |
| `playback.release` | 1,015 | 9.5 ms | 71 ms | 175 ms | 494 ms |
| `playback.heartbeat` | 3,096 | 8.2 ms | 59 ms | 152 ms | 560 ms |
| `playback.qoe` | 1,015 | 9.3 ms | 68 ms | 139 ms | 538 ms |

Reading it:
- **The objectives held at 200 viewers** (p99 357 ms, no server errors), but the tail grew fast:
  p95 rose 5–10× while traffic rose 2.8×. That is a queue forming — the knee of the curve is near.
- **The machine, not only the API, was the limit.** The API used 1.2 of 2 cores while k6, Postgres
  and the worker shared the rest. Capacity numbers for production need the load generator on its
  own machine; on this runner, ~200 viewers is the ceiling of what can be measured.
- **The worker's 86 % CPU is most likely the outbox** (not yet profiled): playback actions emit
  domain events that Celery delivers. Under load it competes with the API for the same cores — in
  production they belong on separate hosts (the compose file already runs them as separate services).
- **Home rails are the costliest read under load** (p99 700 ms, 70 % of the budget; several queries
  per call) — the first candidate for a short server-side cache when capacity matters.
- **The 429s:** the run fails on any 429 by design. The likeliest source is `playback.release`
  (5/s per IP): the input check keeps the *average* under 4/s, but during the ramp viewers start in
  step and their releases cluster. Follow-up: report 429s per endpoint, and either stagger viewer
  starts or lower the input bound — the test's pacing, not the system, is what failed.
