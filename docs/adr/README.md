# Architecture Decision Records

Short records of decisions that shape the code: the context, what was decided, and what it costs.
One file per decision, numbered in the order they were written. A superseded record stays, marked
"Superseded by ADR-NNNN".

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-player-track-model-and-post-play.md) | Player: one track model for every engine; time-based post-play | Accepted |
| [0002](0002-i18n-feature-owned-catalogs.md) | Internationalisation: feature-owned catalogs, account language, codes over sentences | Accepted |
| [0003](0003-coverage-per-module-ratchet.md) | Coverage measured per module, with floors that only go up | Accepted |
| [0004](0004-tmdb-as-a-metadata-source.md) | TMDB is a metadata source, never the owner of a title | Accepted |
| [0005](0005-one-command-docker-demo.md) | A one-command Docker demo with generated secrets, separate from production | Accepted |
| [0006](0006-security-headers-csp-hsts.md) | Security headers: one CSP source for nginx and the browser tests; HSTS only over HTTPS | Accepted |
| [0007](0007-browser-tests-under-production-csp.md) | Browser tests run the production build under the production CSP and fail on any violation | Accepted |
| [0008](0008-observability.md) | Observability: correct metrics, one trace per request, SLOs and alerts as tested code | Accepted |
| [0009](0009-load-testing.md) | Load testing: real client pacing, SLO thresholds, limits left on | Accepted |
