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

## Provider reference

Official documentation:

- Spotify Web API: <https://developer.spotify.com/documentation>
- YouTube Data API: <https://developers.google.com/youtube/data>
- ListenBrainz API: <https://listenbrainz.readthedocs.io/en/latest/>
- MusicBrainz API: <https://musicbrainz.org/doc/MusicBrainz_API>

> **Verify before implementing.** The constraints below are known as of the start of the project, and
> providers change their terms, quotas and endpoint access frequently. Re-check each provider's
> current documentation and terms before building its adapter, and record what you confirmed here.

### Spotify

- **Auth:** OAuth 2.0 Authorization Code flow (with PKCE).
- Development mode allows only an allow-listed set of users, and extended quota access is restricted.
  Check current eligibility before committing to Spotify as the first integration.
- The recommendations, audio-features/analysis and related-artists endpoints are unavailable to new
  apps. This matches the spec's rule not to depend on them.
- Redirect URIs must use HTTPS or a loopback IP literal (`http://127.0.0.1:<port>`), not `localhost`.

### YouTube Data API v3

- **Auth:** Google OAuth 2.0 for account operations. An API key is enough for public data.
- Daily quota is 10,000 units by default. `search.list` costs 100 units; insert, update and delete
  calls cost about 50 each. Budget quota per user action.
- The Developer Policies restrict how long API data may be stored without refreshing it.
- Playlist inserts are not idempotent: de-duplicate before inserting so exports are retry-safe.

### ListenBrainz

- **Auth:** a per-user token, sent as `Authorization: Token <token>`.
- Rate limits are communicated in `X-RateLimit-*` response headers; honour them.
- Listening history is personal data: import it only with explicit consent.

### MusicBrainz

- **Auth:** none for reads.
- The limit is about 1 request per second per IP. Requests also need a meaningful `User-Agent`
  (application, version and contact), or they are rejected.
- Core data is CC0; check the licensing of supplementary data. Use MBIDs and ISRCs for entity
  resolution.

The adapters will live in `backend/app/domains/integrations/` behind the `MusicProvider` interface,
with capability detection (§10.1).
