# ADR-018: Music platform integrations — adapters, encrypted tokens, consented imports and retry-safe exports

- **Status:** Accepted
- **Date:** 2026-11-17

## Context

Milestone 5 connects SONIQUEO to ListenBrainz, MusicBrainz, Spotify (where permitted) and
YouTube (spec §10, ADR-006). Acceptance criteria: provider-specific failures are isolated,
tokens are securely managed, playlist export is retry-safe, provider quotas are respected.

The providers changed in 2026: Spotify's Development Mode now requires the app owner to have
Premium, serves at most five allow-listed accounts and moved its playlist endpoints
(`/me/playlists`, `/playlists/{id}/items`); YouTube's default quota is 10,000 units a day with
`search.list` at 100 units; ListenBrainz asks clients to read recent listens only and use its
export API for whole histories (INTEGRATIONS.md, verified 2026-11-17).

## Problem

How are provider accounts linked and their tokens kept safe? How does external history enter the
taste profile without breaking the event model or privacy rules? How is an export made safe to
retry when providers' write endpoints are not idempotent, and how is a small daily quota
respected? What happens when a provider is down?

## Alternatives considered

1. **Provider SDKs called from the services, tokens in plain columns.** Least code, but a
   database leak exposes every linked account, and provider failures surface anywhere.
2. **A background job queue for every provider operation.** Robust for very large imports, but
   needs a running worker (Celery has no Windows pool) and a polling UI for operations that take
   seconds at SONIQUEO's sizes.
3. **Adapters with declared capabilities, synchronous bounded operations, encrypted tokens, an
   idempotent event import and a stateful export record.**

## Decision

Option 3.

- **Adapters.** One class per provider (`providers/`), declaring its auth kind (token, OAuth,
  none) and capabilities (import history, export playlist, search). Each owns its endpoints,
  rate limiting and error translation into `IntegrationError` types; the service never sees an
  HTTP status. A provider is offered only when the server is configured for it.
- **Tokens.** AES-256-GCM with `INTEGRATIONS_TOKEN_KEY`, the user id and provider as associated
  data (a ciphertext moved to another row does not decrypt), a `v1:` prefix for future rotation.
  Refreshed 60 seconds before expiry and once more when a call is rejected; if that fails the
  connection becomes `reauth_required`. OAuth uses PKCE with a single-use, user-bound `state`
  kept in Redis for ten minutes; the callback goes through the Next.js proxy, so the session
  cookie identifies the user.
- **Imports** are explicit (a consent flag per run), bounded (ListenBrainz: ten pages of 1,000;
  Spotify: 1,000 saved tracks and the last 50 plays) and incremental (a cursor per connection).
  Items are matched to the catalogue by recording MBID, ISRC, then the exact artist-and-title key,
  and stored as ordinary events with `source` set to the provider and an idempotency key derived
  from the provider's item, so repeats are skipped by the existing unique constraint.
  Disconnecting can delete them again. Each run is recorded (`provider_imports`).
- **Exports** keep one `playlist_exports` row per playlist and provider. The remote playlist id is
  saved before any item is written; a re-export (or a retry after a failure) reuses it, finds it
  again by a `[soniqueo:<id>]` marker in its description if the id was lost, and only then creates
  one. Items are made equal to the SONIQUEO playlist with each provider's safest primitive
  (Spotify `PUT` replace, ListenBrainz delete-then-add, YouTube diff). Exported playlists are
  private.
- **Quotas.** YouTube units are reserved atomically in Redis (Lua) per Pacific-time day before
  each call; an export whose worst case exceeds what is left is refused before it starts, and
  exports are capped at 50 tracks. Provider ids found by searching are cached for 30 days
  (`provider_track_ids`), respecting YouTube's limit on storing API data.
- **Isolation.** Every route maps integration errors to `502`, `429`, `409` or `503`; a failed run
  is recorded with its message; no recommendation, catalogue or playlist route calls a provider.
- **Personal data.** The data export lists connections, imports and exports without tokens;
  account deletion cascades to all of them.

## Consequences

- Without `INTEGRATIONS_TOKEN_KEY` no account can be connected (`503`); rotating the key
  requires users to reconnect until key versions are added.
- Spotify serves at most five allow-listed accounts until the app gets extended quota.
- Imports run inside the request: fine for ten pages, but full ListenBrainz histories need the
  export API and a background job later.
- YouTube exports are limited to 50 tracks by the default quota.
- Imported listens are matched only when the catalogue has the recording; unmatched items are
  counted and reported, never guessed.
