# ADR-017: Authentication and the user application — server sessions, a same-origin proxy and honest playback

- **Status:** Accepted
- **Date:** 2026-11-17

## Context

Milestone 4 turns the recommendation engine into an application people use: accounts, onboarding,
a dashboard, discovery, mood mixes, playlists, feedback and taste analytics, in a dark-first
Next.js interface (spec §7 and the Milestone 4 frontend specification). Until now the user API
took the user id in the path and was served only in local and test environments (ADR-016); it
must be replaced by authenticated `/users/me/…` routes with ownership checks (spec §12.3).

Constraints: no provider integrations yet (Milestone 5), so TASTIFY cannot play audio; the
catalogue has MusicBrainz release-group ids but no artwork; the spec asks for no tokens in
`localStorage`, accessibility, and loading, empty, error and offline states everywhere.

## Problem

How do users authenticate, and how is the session protected against theft and cross-site
requests? How does the browser reach the API? What does the player do without audio, where does
artwork come from, and how are mood mixes defined without mood labels in the data?

## Alternatives considered

1. **JWT access and refresh tokens held by the browser.** Stateless, but tokens in JavaScript are
   exposed to XSS, revocation needs a deny list anyway, and refresh rotation adds complexity
   without benefit for a single first-party web client.
2. **A hosted identity provider (OAuth/OIDC).** Strong, but an external dependency and account
   for a portfolio project, and still needs a first-party session for the API.
3. **Opaque server-side sessions in an `HttpOnly` cookie, with the API behind a same-origin
   proxy.** The browser never sees a token; sessions are revocable rows; the cookie is
   first-party, so `SameSite=Lax` plus an `Origin` check covers cross-site requests.

## Decision

Option 3.

**Accounts and sessions.** E-mail and password accounts (e-mail stored lower-case, unique).
Passwords: 10–128 characters, no leading or trailing spaces, not the e-mail; hashed with
Argon2id (`argon2-cffi`, rehashed when parameters change); unknown e-mails are checked against a
dummy hash so login timing does not reveal accounts. A login creates a 256-bit random token; only
its SHA-256 hash is stored (`user_sessions`). The cookie `tastify_session` is `HttpOnly`,
`SameSite=Lax`, `Path=/`, `Secure` outside local and test, valid 30 days and extended at most
hourly while in use. Logout revokes the session; a password change revokes every other session;
account deletion removes the user and everything that cascades from it. Both password
confirmations answer a wrong password with `403`: `401` always means "signed out", and the
client answers it by sending the user to the sign-in page.

**Cross-site requests and abuse.** State-changing requests that carry an `Origin` header which
is not an allowed origin are rejected with `403` before routing (browsers send `Origin` on the
cross-site requests CSRF relies on; requests without it, such as server-to-server clients, pass
and still need the session cookie, which `SameSite=Lax` withholds from cross-site subrequests). Login is limited to
10 attempts per account and 30 per client in 15 minutes, registration to 10 per client per hour
(Redis fixed windows, `429` with `Retry-After`). The client address comes from
`X-Forwarded-For` only when the direct peer is a configured trusted proxy (addresses or
networks).

**Same-origin API.** The browser calls `/api/v1/*` on the frontend's own origin; the Next.js
proxy (`src/proxy.ts`) forwards it to `API_PROXY_TARGET`, preserving cookies, `Origin` and the
forwarded client address. The proxy also redirects optimistically (no session cookie on an app
page → `/login?next=…`); the API still authorizes every request. A change of signed-in state
(login, registration, logout, expiry, deletion) is a full page load, so neither the client router
cache nor in-memory data of the previous state survives.

**The development user API is removed.** `/users/{id}/…` and `DEV_USER_API` are gone; every
personal route resolves the user from the session, and other users' playlists answer `404`.

**Playback.** The player keeps a queue and shows the current track with links to listen on
YouTube or MusicBrainz, and states that in-app playback arrives with integrations. It never
simulates playback and records no `play`, `skip` or `complete` events: feedback comes from likes,
dislikes, saves and playlist additions until a real audio source exists.

**Artwork.** Track, album and artist artwork is the Cover Art Archive's front image of the
release group (`coverartarchive.org/release-group/{mbid}/front-500`), loaded by the browser
through the Next.js image optimizer and cached there, never stored by TASTIFY. Cover art is the
rights holders' material, shown as identification of the release (the Cover Art Archive's
purpose); it can be switched off with `COVER_ART_ENABLED=false`. Every image has a deterministic
generated cover underneath, shown while loading and when there is no image.

**Mood mixes.** Eight mood recipes (genres, tempo and danceability ranges from AcousticBrainz)
select tracks by tag affinity; signed-in users get them ranked with their taste and without
tracks they have heard. Language-based collections are out of scope (no reliable language data).

**Frontend.** Next.js App Router with route groups for auth, onboarding and the app shell;
server state in TanStack Query (keys in one module, optimistic feedback and reordering), UI state
in Zustand, forms in React Hook Form with Zod schemas shared with validation of every API
response; design tokens as Tailwind theme variables; Radix primitives for dialogs, menus,
sliders, switches and tabs; Motion with reduced-motion respected; Recharts for the one time
series, with a table view beside it. The muted text colour is `#9A9D93` instead of the
specification's `#74776D`, which falls below WCAG AA contrast (4.5:1) on every surface but the
page background; axe-core checks every page at desktop and phone widths in CI.

**Offline.** Queries pause rather than fail while the browser is offline, feedback and
playlist changes made meanwhile are sent on reconnect, and a banner says so.

**Not in this milestone.** Password reset and e-mail verification need an e-mail delivery
service; they are scheduled with production hardening (Milestone 7).

## Consequences

- Sessions cost a database read per authenticated request (indexed by token hash); acceptable at
  this scale and cacheable later.
- The API and frontend must share an origin in every deployment (the proxy); a separate API
  origin would need CORS with credentials and a different CSRF defence.
- Trusted proxies must be configured per deployment, or rate limits key on the proxy's address.
- Without playback, implicit feedback is sparse until Milestone 5; the taste profile relies on
  declared preferences and explicit feedback for new users.
- Cover art depends on an external service at view time; failures degrade to generated covers.
