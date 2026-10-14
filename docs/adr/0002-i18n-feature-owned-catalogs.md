# ADR-0002 — Internationalisation: feature-owned catalogs, account language, codes over sentences

- Status: Accepted (2026-10)
- Area: frontend `core/i18n`, every feature; backend `shared_kernel.locale`, notifications, identity

## Context

The product shipped in Turkish only, with text hard-coded in components, helpers, the server's
recommendation rows and the e-mails. English had to be added without breaking the modular rules:
features own their code, `shared/` never depends on `core/`, the API stays backwards compatible.

## Decision

1. **A small in-house i18n core** (`core/i18n`, ~200 lines) on the platform's `Intl` APIs: a locale
   store (saved choice → browser languages → Turkish), `defineMessages` catalogs, plurals through
   `Intl.PluralRules`, numbers/dates/money through cached `Intl` formatters.
2. **Each feature owns its catalog** (`features/<id>/i18n.js`, both languages side by side).
   A catalog with a missing language, a missing key or a dropped `{placeholder}` throws a named
   `MessageCatalogError` when it is defined; a test imports every catalog. Manifest labels are
   `catalog.ref(key)` — an unknown key fails at start-up, not on screen.
3. **Pure helpers take the translator** (`factLine(card, t)`, `nextUp(detail, progress, t)`); form
   schemas hold message *keys*, forms render `t(error.message)`.
4. **`shared/` stays i18n-free**: the app injects the few words shared components say through
   `SharedTextProvider` (dependency inversion).
5. **The server sends codes, not sentences**, where the client renders: recommendation rows carry
   `reason_code` + `reason_subject` (the English `reason`/`title` stay for older clients). Plan
   bullets are derived from entitlements instead of the server's Turkish `features`.
6. **One language per account**: `identity_users.locale`, set from `Accept-Language` at sign-up,
   adopted once at sign-in by older accounts, changed with `PUT /auth/me/locale`. The frontend
   reconciles it (`app/LocaleSync`). E-mails are queued with the recipient's locale; templates exist
   per (key, locale), the Turkish original is mandatory and translations must use exactly its
   placeholders (`TemplateLocaleError` otherwise).

## Consequences

- A third language is a catalog per feature plus e-mail variants; nothing structural changes.
- Content metadata (titles, synopses, genre names) is still single-language; it comes with TMDB.
- Admin statistics keys are shown as the API names them (developer-facing).
- Alternative considered: i18next. Rejected for now — two languages, no translator tooling, and
  the definition-time contract above is stricter than its runtime fallbacks. Keys would carry over.
