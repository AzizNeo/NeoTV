# ADR-0010 — From an audit to a rewrite: what was found, and where each finding is handled

- Status: Accepted (2026-10)
- Area: the whole codebase; `migrations/revisions/b2c0de00000{1,2,3}_*`, `tools/cleanup_legacy.py`

## Context

NeoTV started as a working prototype (`IPTV_Project`, "pre-v2"). On 2026-10-09 the whole of it —
backend, migrations, Celery and Redis, transcoder, scripts, CI and the React client — was read line by
line, with import graphs, call chains, transaction boundaries and the client–server contract
cross-checked. The audit recorded **62 findings** in eleven areas, 23 of them P0 (must fix before
anything else). The overall picture:

| Area | Grade | In one line |
| --- | --- | --- |
| Security | F | unauthenticated media proxy, path traversal, plan upgrades without payment, unsigned webhooks, exposed stream keys, token-type confusion |
| Runtime correctness | D | several user-facing endpoints failed deterministically; a second user could not sign in from the same browser |
| Data consistency | D | failed event handlers marked as processed; plan limits defined in three places; a race in the stream limit |
| Async infrastructure | F | two Celery applications; the outbox dispatcher ran on no worker |
| Modularity | C− | the right direction (ports and adapters, import contracts), undone by loaders that swallowed errors |
| Performance | D | requests blocking for 10–30 s on a 6-thread server; media proxied through memory |
| Tests and CI | F | effectively no running tests; CI paths broken on Linux |
| Frontend | C | duplicated auth provider; on-demand playback bypassed authorisation |

The detailed report (in Turkish, about 220 KB) was a working document for the rewrite. It is not
published with the repository: it describes code that is not in it, at a level of detail meant for
fixing, not for reading. This record replaces it.

## Decision

**Rewrite, not patch.** The fixes were architectural, not local, so the backend became a modular
monolith (kernel + modules, contracts enforced by import-linter and fitness tests) and the client a
feature-sliced app with manifests and named contract errors. Data was carried over by an
expand → migrate → contract migration chain (`b2c0de000001` → `000002` → `000003`), and the legacy
tree was removed by `tools/cleanup_legacy.py` (paths in `tools/legacy_paths.txt`).

**Every finding keeps its ID.** Code comments cite them where a design choice answers one (for
example *“only the owner can extend a slot (SEC-08)”*); the index below says what each ID means
and where it is handled now.

## Finding index

✔ = re-checked in the code during the pre-publication review (2026-10-17). The rest are answered by
the v2 design as listed and covered by the test suite as a whole.

| ID | Pri. | Finding (pre-v2) | Handled now | |
| --- | --- | --- | --- | --- |
| SEC-01 | P0 | HLS asset route accepted arbitrary file paths | File names must match the transcoder's patterns; every request needs a signed grant for that stream — `live` | ✔ |
| SEC-02 | P0 | Media proxy without authentication or destination limits | Signed, subject-bound grants; egress guard (private ranges, ports); TLS verified; streamed — `playback/hls_proxy.py`, `kernel/security/egress.py` | ✔ |
| SEC-03 | P0 | Ingest stream keys returned by a public endpoint | Stored as keyed hashes, shown once to an admin — `live/services.py` | ✔ |
| SEC-04 | P0 | Plan upgrade without payment; unsigned webhook | Provider checkout; signature-verified, idempotent webhooks; simulated completion only in `dev`/`test` — `billing` | ✔ |
| SEC-05 | P0 | Token type not checked; suspended users kept access | Typed tokens; token version and active flag checked on every request — `kernel/security/tokens.py`, `identity` | ✔ |
| SEC-06 | P1 | Brute-force protection off; account enumeration | Login throttling, optional CAPTCHA, identical answers for unknown accounts — `identity` | ✔ |
| SEC-07 | P0 | DRM keys stored and served in clear; renew IDOR | Envelope encryption, rotating KEKs (MultiFernet); legacy keys not migrated — `drm/vault.py` | ✔ |
| SEC-08 | P1 | Heartbeat IDOR; origin URL reachable by viewers | Only a slot's owner extends it; origin URLs never reach the browser (browser-tested) — `playback` | ✔ |
| SEC-09 | P1 | Playlist endpoints without authorisation; synchronous fetch | Admin-only; imports run as Celery tasks — `catalog` | |
| SEC-10 | P1 | Hard-coded anti-leech secret; MD5 | HMAC-SHA256 grants keyed from settings, constant-time comparison — `kernel/security/signed_url.py` | ✔ |
| SEC-11 | P1 | Redis and Flower exposed; default passwords | No Flower; Redis on loopback only; required secrets, placeholders refused at boot — compose files, `kernel/settings.py` | ✔ |
| SEC-12 | P0 | Profile PIN check always passed | Hashed PINs, verified — `profile` | ✔ |
| RT-01 | P0 | Transcoder failed to import | Platform-neutral process supervision — `live/transcoding.py` | |
| RT-02 | P0 | Favourites and history crashed | Rebuilt — `library` | |
| RT-03 | P0 | Playlist listing crashed | Rebuilt — `catalog` | |
| RT-04 | P0 | Trending not serialisable | The cache boundary rejects ORM objects loudly — `kernel/cache/stampede.py` | |
| RT-05 | P0 | Profiles required but not implemented | Profiles and profile tokens — `profile` | |
| RT-06 | P0 | Device uniqueness broke a second user's sign-in | Per-user keyed device ids, atomic upsert — `kernel/security/device_keys.py`, `devices` | |
| RT-07 | P0 | Migration chain broken | One linear chain, tested from empty and as an upgrade — `tests/migrations` | |
| RT-08 | P1 | Launchers broken; system-wide process kill | Own process tree only — `tools/devctl.py`, `start.py` | |
| RT-09 | P1 | A Redis outage took the catalogue down | Only database failures trip the catalogue breaker — `catalog/services.py` | |
| RES-01 | P1 | Circuit breaker state machine wrong | Rewritten and tested — `kernel/resilience/circuit_breaker.py` | |
| DATA-01 | P0 | Race in the stream limit; no release | One atomic Redis script per change; release by token (beacon-safe) — `playback/concurrency.py` | ✔ |
| DATA-02 | P1 | DRM licensing counted without locking | Locked count — `drm/services.py` | |
| DATA-03 | P1 | Plan limits defined in three places | One plan catalogue — `billing` | |
| DATA-04 | P1 | Subscription lifecycle incomplete | Subscription state machine — `billing` | |
| DATA-05 | P1 | Idempotency key not bound to the body; blocking | Key bound to the request — `kernel/resilience/idempotency.py` | |
| DATA-06 | P1 | Playlist refresh destroyed channel ids | Sync keeps identities — `catalog` | |
| DATA-07 | P1 | Import classification, atomicity, duration | Asynchronous, atomic import — `catalog/tasks.py` | |
| DATA-08 | P1 | SQLite under concurrency | PostgreSQL in production; SQLite for local development only | |
| DATA-09 | P2 | Naive datetimes | Aware UTC throughout; converted by the data migration | |
| DATA-10 | P2 | Favourite uniqueness and toggle semantics | Idempotent add and remove — `library` | |
| ASY-01 | P0 | Two Celery applications; outbox never ran | One application — `kernel/celery_factory.py` | |
| ASY-02 | P0 | Event bus swallowed handler errors | Outbox and inbox with retries and dead letters, alerted on (ADR-0008) — `kernel/outbox` | |
| ASY-03 | P1 | Dispatcher outside a transaction and app context | `kernel/outbox` | |
| ASY-04 | P1 | A "sync" task that did nothing | Real tasks — `catalog/tasks.py` | |
| ASY-05 | P1 | Modules and listeners loaded silently | The registry fails at boot with named errors — `kernel` | |
| ASY-06 | P2 | Background jobs duplicated | Celery tasks; the legacy job table is not migrated | |
| STR-01 | P0 | FFmpeg stderr deadlock | stderr drained continuously — `live/transcoding.py` | |
| STR-02 | P1 | Transcode orchestrator lifecycle | Redis leases — `live/orchestrator.py` | |
| STR-03 | P1 | Platform and encoder dependency | Process groups on POSIX and Windows — `live/transcoding.py` | |
| STR-04 | P1 | Cold start held requests open | `503` + `Retry-After` while a stream warms up — `live` | ✔ |
| PERF-01 | P1 | Thread starvation | gunicorn threads; proxied media streamed, not buffered — `playback/hls_proxy.py` | |
| PERF-02 | P2 | Synchronous access log | Structured logging | |
| PERF-03 | P2 | N+1 queries | Rewritten queries | |
| PERF-04 | P2 | Import-time side effects | Nothing wired until configured, e.g. tracing — `kernel/observability/tracing.py` | |
| CFG-01 | P0 | `.env` never applied; hard-coded signing secret | Typed settings; placeholder secrets refused at boot — `kernel/settings.py` | ✔ |
| CFG-02 | P1 | Virtualenv in the project root; hygiene | `.gitignore`; `tools/cleanup_legacy.py` | |
| CFG-03 | P1 | Docker Compose did not work | Images built and the demo smoke-tested in CI (ADR-0005) | |
| FE-01 | P1 | Two auth providers | One — `core/auth/AuthProvider.jsx` | |
| FE-02 | P0 | On-demand playback bypassed authorisation | Every playback opens a server session — `usePlaybackSession.js` | |
| FE-03 | P0 | Fake `Authorization` header on media requests | No credentials on media; signed URLs — player engines | |
| FE-04 | P1 | Token handling | Access token in memory, refresh in an httpOnly cookie — `core/auth/tokenStore.js` | |
| FE-05 | P1 | Client–server contract drift | operationId client, `npm run check:api` before every build | |
| FE-06 | P2 | Registration form sent the wrong data | `RegisterPage.jsx` | |
| FE-07 | P2 | Player lifecycle leaks | Engine abstraction with deterministic cleanup — `CustomPlayer.jsx` | |
| FE-08 | P2 | Layering; hard-coded routes and navigation | Feature manifests; layer rules in ESLint | |
| HYG-01 | P2 | Duplicate implementations | Removed with the legacy tree | |
| HYG-02 | P2 | Components never wired | Removed with the legacy tree | |
| HYG-03 | P3 | Other hygiene | Removed with the legacy tree | |
| TEST-01 | P0 | No running tests | Backend, frontend, browser, load and alert-rule tests in CI | |
| TEST-02 | P0 | CI broken; layer contract violated by its own code | `ci.yml`; import contracts enforced | |

## Upgrading a pre-v2 installation

Run from the project root with the virtualenv active.

1. `python -m tools.devctl db-backup` — timestamped copy of `instance/database.db`. **Do not skip:**
   step 5 cannot be undone after `000003`, which drops the legacy tables and refuses to downgrade.
2. `pip install --require-hashes -r requirements-dev.lock`
3. `python -m tools.devctl init-env` — creates `.env` or adds missing keys; fixes the old
   `DATABASE_URL` to point into `instance/`.
4. `python -m tools.devctl doctor` — settings, database, Redis, ffmpeg and migration state.
5. `python -m tools.devctl migrate` — schema (`000001`), data (`000002`), legacy tables dropped (`000003`).
6. `python -m tools.devctl create-admin` — creates an admin or promotes an existing account.
7. `python -m tools.cleanup_legacy`, then `--apply` — dry run first; `--apply` moves legacy files to
   `.legacy_backup/<timestamp>/` (reversible).
8. `cd frontend && npm ci && npm run build`
9. `python -m tools.devctl run`

### Data deliberately not migrated

| Data | Why |
| --- | --- |
| Refresh tokens and web sessions | Authentication is new; everyone signs in once after the upgrade. |
| Device fingerprints | v2 device keys are keyed hashes that cannot be recomputed from legacy rows; legacy devices are kept as inactive history. |
| RTMP ingest keys | v2 stores only keyed hashes. Rotate keys in Admin → Live (external sources keep working). |
| DRM content keys | Pre-v2 stored and served them in clear, so they must be treated as compromised; protection is re-applied with fresh, envelope-encrypted keys. Policies are migrated. |
| `access_log`, `background_job` | Operational noise. |
| Orphaned, duplicate or invalid rows | Skipped, and counted by reason in the migration output (`orphan`, `duplicate`, `non_http_url` …). |

## Consequences

- The audit's IDs stay meaningful: a comment such as *(RT-06)* leads here.
- The full report is no longer in the working tree. It remains in git history, which is acceptable:
  it describes code that this repository does not contain, and every P0 security finding is
  re-checked above.
- New problems are recorded where they are fixed — tests, ADRs, runbooks — not in a separate audit
  document that drifts from the code.
