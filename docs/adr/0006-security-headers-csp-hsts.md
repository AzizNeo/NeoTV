# ADR-0006 — Security headers: one CSP source for nginx and the browser tests; HSTS only over HTTPS

- Status: Accepted (2026-10)
- Area: `deploy/nginx/security-headers.conf`, `app/kernel/http/request_context.py`, `frontend/vite.config.js`

## Context

The SPA had no Content-Security-Policy and no HSTS. A CSP is the second wall against XSS: even if
an attacker gets markup into a page, the browser refuses to run script that is not ours. It only
works if it is strict (no `'unsafe-inline'`, no `'unsafe-eval'`) and if it is the policy the app
was actually tested under — a CSP that differs between test and production breaks production.

## Decision

- **One source.** The SPA's headers live in `deploy/nginx/security-headers.conf`, one
  `add_header` per line. nginx includes it in every location that serves the app (nginx drops
  inherited `add_header`s in a location that declares its own — a test pins the includes);
  `vite preview` parses the same file, so the browser tests run under the production policy.
- **The policy.** `script-src 'self'` and `style-src 'self'` with no exceptions;
  `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`, `frame-ancestors 'none'`;
  `worker-src 'self' blob:` (hls.js transmuxes in a blob worker); `img-src … https:` (channel logos
  come from imported M3U lists, artwork from TMDB); `media-src`/`connect-src 'self' https: blob:`
  because a channel may use *direct* delivery, where the player fetches the CDN itself.
- **The API** answers `default-src 'none'; frame-ancestors 'none'; …` on `/api/*`: it returns
  data, never documents.
- **HSTS** (`max-age` 1 year, `includeSubDomains`, no `preload`) only when the request arrived
  over HTTPS — via the trusted proxy (`X-Forwarded-Proto`, honoured only with
  `TRUSTED_PROXY_COUNT`) in Flask, via a `map` in nginx. Plain-HTTP setups (the local demo) are
  unaffected. `HSTS_MAX_AGE_S=0` turns it off. `preload` is left to the operator: leaving the
  browsers' preload list takes months.
- Two code changes made the strict policy possible instead of loosening it: Zod runs `jitless`
  (it otherwise probes `new Function`), and fonts are never inlined as `data:` URIs.

## Consequences

- `connect-src`/`media-src https:` is wider than `'self'`. It is the price of direct delivery;
  script execution — what XSS needs — stays locked to our own files. An operator who never uses
  direct delivery can narrow both to `'self' blob:`.
- The dev server has no CSP (Vite's hot reload injects inline scripts); `npm run preview` and the
  Playwright suite run the production build under the real policy and fail on any violation.
- A new third-party script or style (analytics, a font CDN) must be a deliberate change to the
  snippet, reviewed as such — the tests reject `'unsafe-*'` and wildcards outright.
