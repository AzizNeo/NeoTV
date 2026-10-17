# ADR-0007 — Browser tests run the production build under the production CSP and fail on any violation

- Status: Accepted (2026-10)
- Area: `frontend/e2e/`, `frontend/playwright.config.js`, `tools/e2e_server.py`, CI job `e2e`

## Context

Unit tests (Vitest, jsdom) check logic but not the assembled app in a browser: routing, the
production bundle, real media playback, and the CSP of ADR-0006 — which only a real browser
enforces. A CSP that nobody tests either breaks production or gets loosened "temporarily".

## Decision

- **Playwright, Chromium**, against the **production build** served by `vite preview`, which
  serves the production security headers (parsed from the nginx snippet).
- **A fresh backend per run** (`python -m tools.e2e_server`): empty SQLite, in-process Redis,
  eager Celery, migrations, a test-only admin, the demo content. No test depends on leftovers.
- **Global guards in the `page` fixture**: every test also fails on a CSP violation (reported to
  the test process through `exposeFunction`, so navigation loses nothing) or an uncaught page
  error. Tests that provoke the policy on purpose opt out explicitly and assert the violation.
- **Behaviour, not implementation**: selectors are roles and visible labels, the way a user (and
  a screen reader) finds things; a test that needs a CSS class is a sign the UI lacks a name.
- One test needs the internet (real HLS playback of a public test stream); `E2E_OFFLINE=1` skips
  it locally. CI always runs it. The proxy test runs offline too: it asserts that the browser
  never contacts the origin host of a proxied stream.

## Consequences

- The suite found a real bug on its first run: under React Router v7 relative links inside the
  `/admin/*` splat route resolved from the full URL, so admin tabs nested (`/admin/overview/
  catalog/…`). Links are now absolute from one constant (`features/admin/paths.js`).
- CI time grows by a few minutes (browser download + build); failures upload the HTML report and
  traces, and the `github` reporter annotates them on the run page.
- **Isolation over cleanup.** A test that changes per-account state (stream slots, the saved
  language, sign-out) gets `viewer`: a fresh account registered through the public API for that
  test alone. The first version shared one admin; a session left open by one playback test made
  the next hit the plan's one-stream limit whenever the release beacon was late — flaky in CI,
  green on retry. Waiting for cleanup treated the symptom; giving each test its own state
  removed the dependency. Read-only admin checks still share the seeded admin.
- **Flaky is failing.** CI retries once (for a second trace) but `failOnFlakyTests` turns a
  pass-on-retry into a failure, so flakiness cannot hide behind a green build.
- Accessibility (2026-10): `e2e/accessibility.spec.js` runs axe (WCAG 2.2 AA) on every page in the light
  and the dark theme; any violation fails CI. Contrast differs per theme, so both are checked.
