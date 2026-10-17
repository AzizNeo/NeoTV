# Contributing to NeoTV

Setup and the quality gates are in the [README](README.md#getting-started) (they are what CI runs).
This page is the checklist for **adding** things without breaking the architecture: every rule below
is enforced by a tool, and a broken rule stops with a named error instead of failing silently.

Security issues: please do not open a public issue — see [SECURITY.md](SECURITY.md).

## The rules in short

**Backend** — `app/kernel/` (container, module registry, manifests, capabilities, extension points,
outbox/inbox, unit of work, `endpoint()`, OpenAPI) and `app/modules/<module>/` (`manifest.py`,
`api.py` as its public contract, `domain.py`, `services.py`, `models.py`, `http.py`, `handlers.py`,
`tasks.py`). `app/shared_kernel/` holds pure helpers every module may use.

- Modules talk in one of three ways: use a capability (`CapabilityIndex.optional(...)`), publish an
  event to the outbox that another module's inbox subscribes to, or contribute to an extension point
  (`drm.license_issuers`, `admin.abuse_rules`, `notifications.templates` …).
- **No direct imports between modules** — enforced by import-linter (`.importlinter`).
- **Every HTTP route goes through `endpoint()`**: authentication, rate limit, permissions, profile,
  idempotency, validation and the response contract are declared in one place and written to OpenAPI.
- `DISABLED_MODULES=recommendations,drm` turns modules off. A module that requires a disabled one
  stops the boot with `MissingDependencyError`; optional dependencies switch off quietly.

**Frontend** — `src/core/` (operationId API client, auth, feature kit, i18n), `src/shared/`
(presentation only; it does not even import `core`), `src/features/<feature>/` (`manifest.js` +
`index.js` as its public API), `src/app/` (composition root: router, shell, providers, bootstrap).

- Layer rules are enforced by ESLint; a feature imports another feature only through its `index.js`.
- API calls are always `api.call('<operationId>', { params, query, body })`; `npm run check:api`
  (part of `npm run build`) fails if the code calls an operation the backend does not expose.
- At start-up `/api/v1/health/info` says which backend modules are on; a feature whose module is off
  leaves the menu and the routes.

## Adding a backend module

1. `flask --app app.wsgi kernel new-module <name>` — copies `app/modules/_template`; the skeleton boots as is.
2. Add it to `INSTALLED_MODULES` in `app/modules/__init__.py`.
3. Fill in `provides`, `requires`, `subscribes` and `error_map` in its `manifest.py`.
4. `flask --app app.wsgi db revision --autogenerate`, then review the migration by hand.
5. `python -m tools.devctl openapi` to refresh `openapi/openapi.json`, then `cd frontend && npm run gen:api`.
6. The quality gates must pass. Fitness tests reject undocumented error codes in responses, routes that
   bypass `endpoint()`, and a stale OpenAPI file.
7. Give the module a coverage floor in `pyproject.toml` (`[tool.neotv.coverage]`) — CI refuses a module
   without one (ADR-0003).
8. A new metric must appear on the Grafana dashboard and a new alert needs a runbook section, or CI
   fails (ADR-0008).

## Adding a frontend feature

1. Create `src/features/<name>/manifest.js` with `defineFeature({ id, backendModule, requires, routes, nav, slots, contributes })`.
2. Export what other code may use from its `index.js`.
3. Add one line to `src/features/index.js`.
4. To put something on another feature's screen, contribute to a slot it declares: `home.rows`,
   `content.actions`, `player.observers`, `account.sections`, `shell.user`.
5. Texts go in the feature's own catalogue, in every supported language (ADR-0002).

Contract violations stop with a named error, shown by `BootError` instead of a blank page:

| Error | When |
| --- | --- |
| `FeatureContractError` | a manifest is invalid |
| `DuplicateRouteError` | two features claim the same path |
| `MissingFeatureError` | a required feature is off or not installed |
| `UnknownSlotError` | a contribution targets a slot nobody declared |

## Adding an admin tab

Add an entry to `src/features/admin/sections/registry.js` and a section file next to it. Its `module`
field names the backend module whose absence hides the tab.

## Adding an e-mail template

1. In the sending module, create `emails.py` with `EmailTemplate(key="<module>.<name>", subject=..., text=..., html=...)`.
   Every `{field}` placeholder is required; values placed in the HTML body are escaped.
2. Register it in the module's manifest: `ExtensionSpec("notifications.templates", "app.modules.<module>.emails:templates")`.
3. Get the mailer with `CapabilityIndex.optional("notifications.email")` and call
   `queue(to=..., template=..., context=...)` **inside your own `with uow:` block**, so the e-mail is stored
   atomically with the change that caused it.

An unknown template or a missing or extra field fails by name (`EMAIL_TEMPLATE_UNKNOWN`,
`EMAIL_TEMPLATE_CONTEXT`). With the notifications module off, template contributions drop out.

## Adding an e-mail provider (Resend, Postmark …)

1. Write a class with a `name` and `send(message: RenderedEmail)`. Raise `PermanentDeliveryError` for
   permanent failures; any other exception is retried by the outbox with back-off.
2. Register it at the `notifications.email_senders` extension point and set `EMAIL_BACKEND=<name>`.
   An unknown name stops the boot with the list of available senders.

## E-mail and account recovery

| Environment | Setting | Behaviour |
| --- | --- | --- |
| Development | `EMAIL_BACKEND=console` (default) | Written to `var/mail/<id>.eml`; links are printed to the console. |
| Production | `EMAIL_BACKEND=smtp` + `SMTP_HOST/PORT/SECURITY/USERNAME/PASSWORD` + `EMAIL_FROM` | `console` and `memory` are refused. SMTP 5xx is permanent, 4xx is retried. |
| Tests | `memory` | Tests read e-mails from memory. |

- **Sign-up** with an e-mail sends a verification link, valid for 48 hours.
- **Forgot password** answers the same whether or not the account exists; the link is single-use and
  valid for 30 minutes.
- **After a reset** every session is signed out and the owner is told by e-mail.
- Tokens are stored only as SHA-256 hashes. The secret travels in the link's `#token=` fragment, so it
  never reaches server logs or a `Referer` header. Message bodies are deleted after sending; an hourly
  job clears any body older than 24 hours.

## Dependency updates

Dependabot opens weekly pull requests (`.github/dependabot.yml`). npm and GitHub Actions updates are
complete as they arrive. A **Python** update changes `requirements*.txt` only: run
`python -m tools.lock_deps` on its branch to regenerate the hash-locked `requirements*.lock` files
(CI's "Locks are current" step fails until then), review the lock diff and push it.

## Commits and decisions

- One concern per change; the message says what changed and why.
- A decision with alternatives goes into an ADR (`docs/adr/`, numbered, indexed in its README).
