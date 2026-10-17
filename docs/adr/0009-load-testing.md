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
