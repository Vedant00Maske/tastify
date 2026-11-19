# TASTIFY — Music Platform Integrations

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§10).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 10. Music Platform Integration Design

### 10.1 Provider Abstraction

Define a common provider interface.

MusicProvider:

- authorize()
- refresh_token()
- search_tracks()
- get_track_metadata()
- get_user_library()
- export_playlist()
- disconnect()

Not all providers will support every operation.

Use capability detection rather than assuming every integration has identical functionality.

### 10.2 Spotify

Potential functionality:
- OAuth.
- Permitted profile and library data.
- Track metadata.
- Playlist creation.
- Playlist updates.
- Playback integration where eligible.

Important restriction:

Spotify Development Mode has significant access restrictions. We must check current eligibility and endpoint availability before committing to any particular integration.

The recommendation engine must not depend on Spotify's proprietary Recommendations API or Audio Features API.

### 10.3 YouTube

Potential functionality:
- Video and music discovery.
- Playlist creation.
- Playlist item insertion.
- External playback links.

Use OAuth and official APIs for account-level operations.

Account for:
- API quotas.
- Authorization scopes.
- Rate limits.
- Provider errors.
- Duplicate playlist entries.

### 10.4 Open Music Ecosystem

Potential integrations:
- ListenBrainz.
- MusicBrainz.

Use these to support music metadata and permitted listening-history workflows.

For each provider, maintain:
- Provider documentation.
- Usage restrictions.
- Attribution requirements.
- Data retention requirements.
- Rate limits.
- Commercial-use eligibility.

---

## Implementation (Milestone 5)

Design: [ADR-018](ADR/ADR-018-music-platform-integrations.md). Code:
`backend/app/domains/integrations/` (adapters in `providers/`, one per platform, behind the
`MusicProvider` interface with declared capabilities).

| Provider | Account | Import | Export | Other | Enabled when |
| --- | --- | --- | --- | --- | --- |
| ListenBrainz | personal user token | newest listens (plays), incremental | private playlist of recording MBIDs | | always (token key set) |
| Spotify | OAuth + PKCE | saved tracks (likes), recently played (plays) | private playlist, tracks found by ISRC | | `SPOTIFY_CLIENT_ID` |
| YouTube | Google OAuth + PKCE | | private playlist, at most 50 tracks | | `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` |
| MusicBrainz | none | | | recording search beyond the catalogue | always |

**Rules every adapter follows**

- *Failures are isolated.* Provider errors become typed integration errors: `502` (provider
  failed), `429` (rate limited, with `Retry-After`, or quota used up), `409` (reconnect needed),
  `503` (not configured on this server). No other feature calls a provider.
- *Tokens are protected.* Access and refresh tokens are encrypted with AES-256-GCM
  (`INTEGRATIONS_TOKEN_KEY`), bound to their user and provider, never returned by the API or the
  data export, refreshed shortly before expiry and once more when rejected. A connection that
  cannot be refreshed is marked `reauth_required`.
- *Imports need consent and are idempotent.* Each import asks for explicit consent. Items become
  ordinary events (`source` = the provider) with a stable idempotency key, so re-importing is a
  no-op; ListenBrainz and Spotify's recently played continue from the newest item imported.
  Matching to the catalogue: recording MBID, then ISRC, then the exact artist-and-title key;
  never fuzzy. Disconnecting can delete everything imported from that provider.
- *Exports are retry-safe.* One `playlist_exports` row per playlist and provider stores the
  remote playlist id before it is filled. Re-exporting updates the same playlist (ListenBrainz:
  remove all items and add them again; Spotify: `PUT` replaces the items; YouTube: insert only the
  missing videos, delete only the extra ones). If the id is lost, the playlist is found again by
  the `[tastify:<playlist id>]` marker in its description.
- *Quotas are respected.* MetaBrainz services: one request per second, `X-RateLimit-*` headers
  honoured. YouTube: every call reserves its units in a Redis counter that resets at midnight
  Pacific time, and an export whose worst case does not fit in what is left is refused before
  any call. Provider ids found by searching (Spotify, YouTube) are cached for 30 days.

## Provider reference

Official documentation:

- Spotify Web API: <https://developer.spotify.com/documentation>
- YouTube Data API: <https://developers.google.com/youtube/data>
- ListenBrainz API: <https://listenbrainz.readthedocs.io/en/latest/>
- MusicBrainz API: <https://musicbrainz.org/doc/MusicBrainz_API>

> **Verified on 2026-11-17** against the providers' current documentation (sources below).
> Providers change their terms, quotas and endpoint access often: re-check before relying on a
> detail, and update this section with the date.

### Spotify

- **Auth:** OAuth 2.0 authorization code with PKCE (no client secret needed). Redirect URIs must
  use HTTPS or a loopback IP literal (`http://127.0.0.1:<port>`), not `localhost`.
- **Development Mode (since 11 February 2026 for new apps, 9 March 2026 for existing ones):** the
  app owner needs an active Premium subscription; at most 5 allow-listed Spotify accounts may use
  the app (others get `403`); up to 25 client ids per developer since July 2026, sharing one quota.
  Extended quota mode is not affected. TASTIFY explains the `403` to the user.
- **Endpoints used:** `GET /me`, `GET /me/tracks`, `GET /me/player/recently-played`,
  `GET /search` (`isrc:` filter; at most 10 results per request since February 2026),
  `GET /me/playlists`, `POST /me/playlists` (replaces `POST /users/{id}/playlists`),
  `GET /playlists/{id}`, `PUT` and `POST /playlists/{id}/items` (replace `.../tracks`; at most 100
  items per request). Track objects still carry `external_ids.isrc` (removed in February,
  restored in March 2026).
- **Never used:** recommendations, audio features or analysis, related artists (spec §10.2).
- **Rate limits:** a rolling 30-second window (`429` with `Retry-After`); quota exhaustion is a
  `429` whose body says `QUOTA_EXCEEDED`.
- Sources: [February 2026 migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide),
  [quota update, July 2026](https://developer.spotify.com/blog/2026-07-23-web-api-quota-updates),
  [TechCrunch, 6 February 2026](https://techcrunch.com/2026/02/06/spotify-changes-developer-mode-api-to-require-premium-accounts-limits-test-users/).

### YouTube Data API v3

- **Auth:** Google OAuth 2.0 (web application client, PKCE, `access_type=offline` for a refresh
  token), scope `https://www.googleapis.com/auth/youtube`. Disconnecting revokes the grant.
- **Quota:** 10,000 units a day by default. `search.list` costs 100 units, `playlists.insert`,
  `playlistItems.insert` and `.delete` 50, list calls 1. A first export of 50 tracks needs about
  7,550 units in the worst case, which is why exports are capped at 50 tracks.
- The Developer Policies limit how long API data may be stored without refreshing it: found
  video ids are re-checked after 30 days.
- Playlist inserts are not idempotent: TASTIFY lists the playlist's items first and only inserts
  what is missing.
- Source: [quota cost table](https://developers.google.com/youtube/v3/determine_quota_cost).

### ListenBrainz

- **Auth:** the user's token, sent as `Authorization: Token <token>`; `GET /1/validate-token`
  answers `200` with `valid: false` for a bad token.
- **Rate limit:** at most one request per second per application; `X-RateLimit-Remaining` and
  `X-RateLimit-Reset-In` on every response, `429` when exceeded. A `User-Agent` with the
  application and a contact is required.
- **Listens:** `GET /1/user/{name}/listens`, newest first, `count` up to 1,000, paged with
  `max_ts` (exclusive). ListenBrainz asks clients to use this endpoint for recent and incremental
  listens only (about ten pages) and its export API (`POST /1/export/`, a ZIP archive) for full
  histories. TASTIFY imports at most ten pages per run, then continues incrementally; full-history
  import through the export API is a later improvement.
- **Playlists:** `POST /1/playlist/create` with JSPF; the
  `https://musicbrainz.org/doc/jspf#playlist` extension's `public` flag is required; tracks are
  identified by `https://musicbrainz.org/recording/<mbid>`. The response is
  `{"status": "ok", "playlist_mbid": ...}`. `item/add` takes at most 100 recordings;
  `item/delete` takes `index` and `count`.
- Listening history is personal data: imported only with explicit consent.
- Sources: [core API](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html),
  [playlist API](https://listenbrainz.readthedocs.io/en/latest/users/api/playlist.html),
  [export API](https://listenbrainz.readthedocs.io/en/latest/users/api/export.html),
  [JSPF](https://musicbrainz.org/doc/jspf).

### MusicBrainz

- **Auth:** none for reads. About 1 request per second per application, with a meaningful
  `User-Agent` (application, version and contact), or requests are rejected (`503`).
- Core data is CC0; check the licensing of supplementary data. MBIDs and ISRCs drive entity
  resolution.
- Search query: `recording:"<words>"^4 OR (recording:(<words>) AND artist:(<words>))^2`, with
  Lucene syntax in user input escaped. Checked against live results: plain word queries rank
  covers that mention the artist in their title above the recording itself.
