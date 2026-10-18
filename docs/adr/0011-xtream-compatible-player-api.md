# ADR-0011 — Xtream-compatible player API: app credentials bound to a profile, the platform's rules unchanged

- Status: Accepted (2026-10)
- Area: new optional module `xtream`; capabilities `identity.users`, `profile.directory`,
  `profile.context`; events `identity.password_changed`, `profile.profile_deleted`

## Context

Most IPTV apps on smart TVs, set-top boxes and phones (TiviMate, IPTV Smarters, GSE, OTT
Navigator …) do not speak NeoTV's API: they speak the de-facto "Xtream Codes" protocol —
`player_api.php` for the catalogue, `xmltv.php` for the guide, `get.php` for an M3U list, and
stream URLs of the form `/live/<username>/<password>/<id>.<ext>`. Supporting it lets a viewer
watch on a TV without a NeoTV app for every platform.

The protocol has properties a modern platform must not inherit:

- the username and password travel **in every URL** (query string or path), so they end up in
  app logs, proxy logs and screenshots;
- there is no token, no expiry, no second factor and no profile;
- stream URLs are long-lived and shareable.

NeoTV provides **no content**: the API exposes only what the operator has put into the catalogue,
under the same entitlement, rating and concurrency rules as the web player.

## Decision

1. **A separate optional module, `xtream`.** It owns only its credential table and its HTTP
   surface. Everything it serves comes through other modules' capabilities, so plans, the kids
   rating filter, stream slots and signed URLs apply exactly as they do in the web player. Turning
   it off (`DISABLED_MODULES=xtream`) removes the protocol and nothing else.
2. **App credentials, never the account password.** Because the protocol leaks what it carries,
   it carries a generated pair: a 10-character username and a 12-character password from a
   31-character alphabet without look-alikes (no `0/o`, `1/l/i`), so it can be typed with a TV
   remote. The password is shown **once**; the server keeps only an HMAC-SHA256 digest keyed with
   a purpose-bound key (`derive_key("xtream/credentials")`) over username + password. A random
   ~59-bit secret needs no slow KDF; the key makes a leaked table useless; the username in the
   message keeps equal passwords from sharing a digest. Unknown usernames cost the same work as
   known ones.
3. **One credential per device, bound to one profile.** The app watches *as that profile*: a kids
   profile's credential sees only kids-rated content, and history and favourites stay per profile.
   A profile with a PIN can be bound only from a session where that PIN was entered (the current
   profile context); otherwise the PIN would be bypassed. Credentials are account settings: a kids
   profile neither lists, creates nor revokes them. At most 10 active credentials per account;
   issuing is rate limited (5 at once, then one per 10 s).
4. **Checked on every request, ended by the events that matter.** Each request re-checks the
   credential, the account (a suspended account is refused; re-activation restores access — a
   suspension is a state, not a revocation) and the profile. A new account password — a reset
   above all — revokes every credential (`identity.password_changed`), and deleting a profile
   revokes the credentials bound to it (`profile.profile_deleted`). Revoked rows are kept, so a
   username is never handed out twice.
5. **Streams never expose the origin.** A stream URL from the app opens a normal playback
   session (plan, rating, concurrency slot) and answers with a redirect to the short-lived signed
   proxy URL the web player uses. HLS (`.m3u8`) only.
6. **Stable numbers for what apps store.** Apps keep stream and category ids (favourites, the
   last channel, hidden groups). A stream id is the content's id with its namespace as the last
   digit (`catalog:12` → `121`, `live:3` → `32`; a new namespace takes a new digit, none is ever
   renumbered). Category names get a numeric id in `xtream_categories` the first time they are
   listed, and keep it. Lists come from read capabilities of the owning modules
   (`catalog.read`, `live.read`), which apply the kids filter themselves.
7. **Inside the API, behind `endpoint()`.** The protocol's routes live under `/api/v1/xtream/`
   like every other route (rate limit, OpenAPI, fitness tests); nginx maps the root paths apps
   call (`/player_api.php` …) onto them. Answers are the protocol's bare JSON, `no-store`.
8. **The protocol's shapes are tested as a contract.** Xtream clients are strict about field
   names and types (numbers as strings, `"0"`/`"1"` flags); each response shape is pinned by tests
   modelled on what the common clients parse.

## Delivery

| Step | Scope |
| --- | --- |
| X1 | This ADR; the module; app credentials — issue (shown once), list, revoke; events; tests |
| X2 | `player_api.php`: account and server info, live/VOD/series categories and lists, VOD and series details |
| X3 | Guide: `get_short_epg`, `get_simple_data_table`, `xmltv.php`; `get.php` M3U |
| X4 | Stream routes → playback session → redirect to the signed proxy; brute-force lockout; credentials never logged; metrics |
| X5 | Account → "TV apps" screen (TR + EN, accessible); an end-to-end test as an Xtream client; README and runbook |

## Consequences

- The owner side is `/api/v1/xtream/credentials` (`GET`, `POST`, `DELETE /<id>`); the answer
  to `POST` is the only place the password ever appears. `server_url` is `FRONTEND_BASE_URL`:
  the public origin, behind which nginx will route the protocol paths (X4).
- The credential cap is checked inside the issuing transaction but without a lock: two parallel
  requests could pass it together. The rate limit makes that practically impossible, and the cap
  is a hygiene limit, not a security boundary.
- `last_used_at` is written at most every 5 minutes: a hint for the owner, not an audit log, and
  not a write on every TV request.
- What the protocol cannot fix stays visible: a credential in a URL can be copied. Per-device
  credentials, instant revocation, stream slots and short-lived signed media URLs bound the damage
  of a leak; the "TV apps" screen (X5) shows when each one was last used.
- Not in scope: catch-up / timeshift (roadmap step 10), the `.ts` container output, and
  notifying the owner by e-mail when a credential is created (a candidate follow-up).
