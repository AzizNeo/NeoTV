# ADR-0003 — Coverage measured per module, with floors that only go up

- Status: Accepted (2026-10)
- Area: CI, `tools/coverage_report.py`, `pyproject.toml`, `frontend/vite.config.js`

## Context

One project-wide percentage hides where the risk is: a well-tested kernel can carry an untested
module, and the number barely moves when a module loses its tests. The codebase is built from
modules with explicit boundaries, so that is the unit worth measuring.

## Decision

- Backend coverage (statements + branches, on PostgreSQL + Redis in CI) is grouped per module
  (`app/modules/<name>`, `kernel`, `shared_kernel`). Each has a **floor** in
  `[tool.neotv.coverage.modules]`, plus a total floor. Below a floor → CI fails naming the module.
  A module without a floor → CI fails (new modules must declare one). Three points above a floor →
  the summary suggests raising it. Floors are never lowered to make a build pass.
- Frontend: Vitest + V8 coverage with global floors in `vite.config.js`; a per-area table (core,
  shared, app, each feature) on the run summary.
- Tables go to the GitHub run summary, HTML reports to artifacts, and badge JSON to a `badges`
  branch (force-pushed by CI, so badge updates never enter the code history).

## Consequences

- The weak spots are named, not averaged away: today `live` (ffmpeg process supervision) and
  `catalog` (remote playlist fetching) on the backend; on the frontend, the screens — which the
  planned Playwright end-to-end tests will cover as user flows rather than with component tests.
- Coverage is a floor, not a target: a line executed is not a behaviour verified, so the floors
  guard against erosion while tests keep asserting outcomes.
- The README badges render once the repository is public (shields.io reads the raw badge JSON).
