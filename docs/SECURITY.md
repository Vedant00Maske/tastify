# TASTIFY — Security and Privacy

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§12).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 12. Security and Privacy Architecture

### 12.1 Authentication

Use OAuth 2.0/OIDC where supported.

For local authentication:
- Argon2id password hashing.
- Secure session cookies.
- Session expiration.
- Refresh and revocation controls.

### 12.2 External Credentials

- Encrypt tokens at rest.
- Never expose tokens to the frontend.
- Never log access tokens.
- Request minimum necessary scopes.
- Support token revocation.
- Separate user tokens from application credentials.

### 12.3 Authorization

Use user-level ownership checks for:
- Playlists.
- Preferences.
- Interactions.
- Personal listening history.
- External connections.

### 12.4 Privacy

Provide:
- Clear consent.
- Data export.
- Account deletion.
- Provider disconnection.
- Data retention controls.
- Personalization opt-out.

Do not collect precise location or unnecessary device information for recommendations.

---

## Accounts and user data (implemented, Milestones 3–4)

Design: [ADR-017](ADR/ADR-017-authentication-and-user-application.md).

- **Authentication (§12.1).** E-mail and password accounts. Passwords are 10–128 characters, not
  padded with spaces and not the e-mail, and are stored only as Argon2id hashes (rehashed when the
  parameters change). Login answers unknown e-mails and wrong passwords identically, with the
  same work (a dummy hash), so it does not reveal which e-mails have accounts.
- **Sessions.** A 256-bit random token per login, stored only as a SHA-256 hash, sent as the
  `tastify_session` cookie: `HttpOnly` (no JavaScript access, nothing in `localStorage`),
  `SameSite=Lax`, `Secure` outside local development and tests. Sessions last 30 days and are
  extended while in use; logout revokes the session, a password change revokes every other one.
- **CSRF.** State-changing requests with an `Origin` that is not one of `CORS_ORIGINS` are
  rejected (`403`); together with `SameSite=Lax` cookies, cross-site forms and scripts cannot act
  for a signed-in user. The browser talks to the API on the frontend's origin through the Next.js
  proxy, so no cross-origin credentials are ever needed.
- **Rate limits (§12.5).** Login: 10 attempts per account and 30 per client address in 15 minutes;
  registration: 10 per client per hour (`429` with `Retry-After`). The client address is taken
  from `X-Forwarded-For` only when the direct peer is in `TRUSTED_PROXIES` (the Next.js server);
  configure it per deployment, or every client shares the proxy's limit.
- **Authorization (§12.3).** Personal routes take the user from the session (`/users/me/…`); there
  is no route that accepts another user's id. Playlists are scoped to their owner and answer `404`
  to anyone else. The Milestone 3 development-only `/users/{user_id}/…` API and `DEV_USER_API`
  were removed.
- **Consent, export and deletion (§12.4).** Registration requires accepting the terms and the
  privacy notice (the time is stored). `GET /users/me/export` returns all of the user's data as
  JSON (no password or token hashes). `DELETE /users/me` (password required) deletes the account
  and cascades to events, preferences, taste profile, playlists and sessions. Collaborative models
  store only item-level data, so no user's history or factors survive in model tables.
- **Personalization opt-out** (§12.4): `personalization_enabled = false` (Settings → Privacy) makes
  recommendations ignore the user's profile and history (only already-heard tracks are still left
  out); explicit feedback is still recorded so it can be turned back on.
- **Data minimization.** Events hold the track, event type, client and server timestamps, an
  optional playback position, session id and source; no device or location data. Sessions keep the
  user agent (shown in the export) for the user's own review; no IP addresses are stored.
- **Browser storage.** Only recent search terms are kept in `localStorage`, on the user's device;
  never credentials, tokens or personal data from the API.
- **Research data separation.** ListenBrainz research listens (pseudonymous) never enter the
  application database; only item-level aggregates derived from them are published (DATA_SOURCES.md).
- **Idempotent ingestion.** `client_event_id` deduplicates retried batches; the batch size is capped
  at 500 events and event types are validated against an allow-list (database CHECK constraint).
- **Third-party requests.** Artwork is loaded from the Cover Art Archive through the Next.js image
  optimizer (the user's browser does not contact it directly); the player's "listen on" links
  open YouTube or MusicBrainz searches only when the user clicks them.

---

## Repository and supply-chain practices (implemented)

- `.env` is git-ignored. `.env.example` contains only placeholders. Provider credentials are read
  from the environment, never from code or config files.
- **Secret scanning:** gitleaks runs in CI over the full history. The pre-commit `detect-private-key`
  hook blocks private keys locally.
- **Dependency auditing:** `pip-audit` (backend) and `npm audit --omit=dev --audit-level=high`
  (frontend) run in CI. Dependabot proposes weekly updates for pip, npm, GitHub Actions and Docker
  base images.
- **Static analysis:** ruff's flake8-bandit (`S`) rules flag common Python security issues.
- **Containers:** production images run as non-root users. In local development, docker compose
  publishes PostgreSQL, Redis and the apps on `127.0.0.1` only.

If a secret is ever committed: **rotate it first**, then remove it from the git history. Deleting it in
a later commit is not enough.
