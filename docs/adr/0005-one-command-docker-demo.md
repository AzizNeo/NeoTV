# ADR-0005 — A one-command Docker demo with generated secrets, separate from production

- Status: Accepted (2026-10)
- Area: `compose.demo.yml`, `tools/demo_env.py`, `tools/demo_smoke.py`, `Demo.bat`, CI job `demo`

## Context

Trying NeoTV meant Python, Node, a `.env`, migrations, an admin account and a seed — about ten
steps. A reviewer (or an interviewer) gives a project one command and two minutes. The
production compose file cannot be that command: it rightly refuses to start without real
secrets, SMTP, a payment provider and DRM keys, and it publishes RTMP.

## Decision

- A separate `compose.demo.yml` (project `neotv-demo`, own volumes) runs the same images as
  production with `ENV=staging`: Postgres, Redis, migrations, API, one worker for every queue
  except transcoding, beat and the nginx edge — published on `127.0.0.1:8080` only. No RTMP
  ingest and no live transcoding (they need ffmpeg-heavy setup to demonstrate).
- **Secrets are generated, not shipped.** A one-shot `secrets` service writes `SECRET_KEY` and
  a random admin password into the demo's `state` volume (mode 0600, atomic write) the first
  time; every container starts through `python -m tools.demo_env exec -- CMD`, which loads
  them and `exec`s the real command (signals still reach it). A public repository therefore
  contains no working demo credential; `down -v` wipes the secrets with the data.
- A one-shot `setup` service creates the admin (`--skip-existing`: never resets a password),
  seeds the legal test content, imports from TMDB only when a token is present (a TMDB failure
  does not fail the demo) and prints a sign-in box. Startup order is explicit:
  `secrets → migrate → setup → web`, with `service_completed_successfully` / `service_healthy`.
- The helper is Python inside the image rather than a mounted shell script: no CRLF breakage
  on Windows checkouts and nothing to bind-mount.
- CI job `demo` starts the demo exactly as documented, runs `tools/demo_smoke.py` through nginx
  (SPA, deep link, artwork, readiness, generated sign-in, seeded content, TMDB module, wrong
  password refused), restarts it and checks that data and secrets survive.

## Consequences

- One more compose file to keep in step with `docker-compose.yml`; both use the same images, and
  the CI job fails if the demo drifts.
- Fixed in passing: the production worker healthcheck pinged `celery@$HOSTNAME` in exec form —
  the variable never expanded and the node names are `default@`/`playlist@`/`transcode@`, so
  workers would always have been reported unhealthy. It now uses shell form and the real names.
- Every long-running demo service has a real healthcheck (`up --wait` treats a disabled one as a
  failure); beat's is "schedule file written in the last 5 minutes".
- The image gains `/var/lib/neotv/state` (writable by the app user) for small single-host state.
- The Postgres password inside the demo network is a fixed `neotv-demo`: Postgres has no
  published port, so it is reachable only from the demo's own containers.
