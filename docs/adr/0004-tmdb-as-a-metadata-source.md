# ADR-0004 — TMDB is a metadata source, never the owner of a title

- Status: Accepted (2026-10)
- Area: new optional module `tmdb`; capability `titles.admin`

## Context

Storefront pages need real names, synopses, artwork and episode lists in Turkish and English.
TMDB has them. But titles are editorial objects: what plays, how it is rated for kids, what is
featured and whether it is published are decisions of the operator, not of a third party.

## Decision

- A separate optional module, `tmdb`, owns only the link table (`tmdb_links`: title slug →
  TMDB id). It never touches titles' tables: it builds a titles *document* and submits it
  through capability `titles.admin` — the same use case as the admin API, so validation,
  source checks and the kids rule apply to imports unchanged.
- **Merge rule** (pure function, unit-tested): an import may change names, synopses and their
  English translations, year, runtime, artwork, genres (+ genre translations), episode names,
  synopses and stills. It never changes the slug, kind, rating, play sources, featured slot or
  published flag of an existing title. Episodes are matched by (season, number). A brand-new
  series arrives unpublished with TMDB's episodes as *announced* (nothing plays yet).
- Calls go through the kernel's egress gateway, allow-listed to `api.themoviedb.org`; the v4
  read token travels in a bearer header (never a URL or a log line); answers are cached in Redis
  for a day (best effort). Without `TMDB_READ_TOKEN` the module answers
  `METADATA_PROVIDER_NOT_CONFIGURED` and the rest of the platform is unaffected; switching
  `titles` off requires switching `tmdb` off too (named boot error otherwise).
- Tests use a fake TMDB with TMDB's response shapes — no network in CI.

## Consequences

- Another provider (OMDb, a studio feed) is another module building the same document.
- Artwork is hot-linked from TMDB's image CDN, which TMDB permits; the attribution TMDB requires
  is exposed by `GET /api/v1/tmdb/status` and shown (localised) under Admin → TMDB. The CSP
  planned in roadmap step 5 must carry `img-src https://image.tmdb.org` — the storefront's
  posters and the admin's search results both load from it.
- Admin → TMDB is the only UI: search (in the admin's language), import into a new or an
  existing slug (the dialog says which editorial fields stay untouched), refresh, unlink. The tab
  appears only when the `tmdb` module is enabled.
- Ratings are not imported: certification systems differ per country and the kids rule must stay
  an editorial decision.
