# TASTIFY — API Specification

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§9).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 9. Recommendation API Design

Base URL: `/api/v1`

### Authentication

POST `/auth/register`

POST `/auth/login`

POST `/auth/logout`

GET `/users/me`

### Preferences

GET `/users/me/preferences`

PUT `/users/me/preferences`

### Music Catalogue

GET `/tracks/search?q=`

GET `/tracks/{track_id}`

GET `/artists/{artist_id}`

### Recommendations

GET `/recommendations/for-you`

GET `/recommendations/mood/{mood}`

GET `/recommendations/artist/{artist_id}`

GET `/recommendations/genre/{genre}`

GET `/recommendations/hidden-gems`

POST `/recommendations/custom`

### Interactions

POST `/interactions`

GET `/interactions/history`

### Playlists

POST `/playlists`

GET `/playlists`

GET `/playlists/{playlist_id}`

PATCH `/playlists/{playlist_id}`

POST `/playlists/{playlist_id}/tracks`

DELETE `/playlists/{playlist_id}/tracks/{track_id}`

POST `/playlists/{playlist_id}/export`

### Integrations

GET `/integrations`

GET `/integrations/{provider}/authorize`

GET `/integrations/{provider}/callback`

DELETE `/integrations/{provider}`

All endpoints must enforce authorization, input validation and appropriate rate limits.

### Example Recommendation Request

POST `/api/v1/recommendations/custom`

Request:

```json
{
  "prompt": "Indie rock with electronic influence",
  "limit": 25,
  "exploration_level": 0.7,
  "exclude_previously_heard": true
}
```

Response:

```json
{
  "request_id": "uuid",
  "model_version": "hybrid-v1",
  "recommendations": [
    {
      "track_id": "uuid",
      "title": "Example Track",
      "artist": "Example Artist",
      "score": 0.91,
      "reason": "Similar musical characteristics"
    }
  ]
}
```

Scores and reasons must be based on actual model outputs and recorded evidence.

Implemented recommendation responses (Milestone 2) follow this shape and add two fields:
`model_versions` (every contributing model version by type, for example
`{"content": "content-20261116-ab12cd34", "popularity": "popularity-20261116-..."}`) and
`strategy` (`similar_tracks`, `similar_artists`, `genre`, `popular` or `trending`). `model_version`
is the version of the model that produced the ranking. When no model of the required type is
active, the endpoints return `503`.

Personalized responses (Milestone 3) add, per item, `discovery` (the artist is new to the user)
and `sources` (every candidate source that retrieved the track: `source`, `retrieval_score`,
`rank`, `model_version`), and at the top level `user_id`, `profile_version`, `ranker`
(`lambdarank`, `weighted` or `cold-start blend`), `composition` (familiar and discovery counts,
the discovery target, exploration mode and diversity policy) and `candidate_sources` (status of
each source: `ok`, `empty`, `skipped` or `failed`, with a detail). A failing source never fails the
request; it is reported here. `strategy` is `personalized`, `cold_start` or `artist_radio`.

```json
{
  "request_id": "uuid",
  "model_version": "hybrid-20261116-…",
  "model_versions": {"hybrid": "…", "collaborative": "…", "content": "…", "popularity": "…"},
  "strategy": "personalized",
  "ranker": "lambdarank",
  "composition": {"familiar": 6, "discovery": 4, "discovery_target": 0.5,
                  "exploration_mode": "balanced", "diversity_policy": "for_you"},
  "candidate_sources": [{"source": "collaborative_mf", "status": "ok", "candidates": 200,
                         "model_version": "collaborative-20261116-…", "detail": null}],
  "recommendations": [{"track_id": "uuid", "title": "…", "artist": "…", "score": 0.97,
                       "reason": "Listeners who play “Creep” also play this",
                       "discovery": false,
                       "sources": [{"source": "collaborative_item", "retrieval_score": 4.21,
                                    "rank": 3, "model_version": "collaborative-20261116-…"}]}]
}
```

---

## Implementation status

| Endpoint                   | Status      | Notes                                                                                                   |
| -------------------------- | ----------- | ------------------------------------------------------------------------------------------------------- |
| `GET /api/v1/health`       | Implemented | Liveness. Returns `{"status": "ok", "version": "..."}` and never touches dependencies.                 |
| `GET /api/v1/health/ready` | Implemented | Readiness. `200` when PostgreSQL and Redis respond within 2 s, otherwise `503` with per-dependency status. |
| `GET /api/v1/tracks/search?q=&limit=` | Implemented (M1) | Fuzzy search over "artist title" (pg_trgm). `q` 2–200 chars, `limit` 1–50. |
| `GET /api/v1/tracks/lookup?provider=&external_id=` | Implemented (M1) | The unified track for any provider identifier (`musicbrainz`, `isrc`, `fma`, ...). 404 if unknown. |
| `GET /api/v1/tracks/{track_id}` | Implemented (M1) | Unified track: credits, album, genres (with source and level), audio features, all external ids, and the licences of contributing sources. |
| `GET /api/v1/artists/{artist_id}` | Implemented (M1) | Artist with genres, external ids and track count. |
| `GET /api/v1/recommendations/similar/{track_id}?limit=&max_per_artist=` | Implemented (M2) | Tracks similar to a seed track: HNSW nearest content embeddings (pool 200), popularity blend, at most `max_per_artist` (default 2) per artist, one version per song (edits and remasters of the seed or of each other are collapsed). 404 for unknown tracks or tracks outside the model. |
| `GET /api/v1/recommendations/artist/{artist_id}?limit=` | Implemented (M2) | The 30 most similar artists (artist embeddings) and their two most popular tracks each, re-ranked with the popularity blend. |
| `GET /api/v1/recommendations/genre/{genre}?limit=` | Implemented (M2) | Tracks whose strongest level-weighted, vote-smoothed tag for the genre is at least 0.25 (a single user vote counts 1/3), ranked by 0.7 x popularity + 0.3 x genre affinity, at most 2 per artist. Genre names are case-insensitive; `-`, `_` and spaces are interchangeable. |
| `GET /api/v1/recommendations/popular?limit=&kind=all_time\|trending&artist_id=` | Implemented (M2) | Most listened tracks over the popularity window, or only reliably rising trends; optionally one artist's tracks. |
| `GET /api/v1/recommendations/artist-radio/{artist_id}?limit=` | Implemented (M3) | The artist's most popular tracks (at most 40% of the list) mixed with tracks of the 30 most similar artists (at most 2 each), diversified with MMR. |
| `GET /api/v1/artists/search?q=&limit=` | Implemented (M4) | Fuzzy artist-name search (pg_trgm); each result has area, top genres, track count and an artwork URL. `q` 2–200 chars, `limit` 1–50. |
| `GET /api/v1/genres?limit=` | Implemented (M4) | The genres with the most tracks (`limit` 1–200, default 60), for browsing. |
| `POST /api/v1/auth/register` | Implemented (M4) | `{email, password, display_name?, accept_terms}`. Password 10–128 characters, no leading/trailing spaces, not the e-mail. `201` with the user and a session cookie; `409` if the e-mail is taken; `422` for a weak password or unaccepted terms; `429` after 10 registrations per client per hour. |
| `POST /api/v1/auth/login` | Implemented (M4) | `{email, password}`; `200` with the user and a session cookie, `401` for any wrong combination (same message and timing for unknown e-mails). `429` after 10 attempts per account or 30 per client in 15 minutes (`Retry-After`). |
| `POST /api/v1/auth/logout` | Implemented (M4) | Revokes the session and clears the cookie (`204`). |
| `POST /api/v1/auth/password` | Implemented (M4) | `{current_password, new_password}`; `204`. Revokes every other session of the user. A wrong current password is `403` (the session is valid; `401` always means signed out). |
| `GET /api/v1/users/me`, `PATCH …` | Implemented (M4) | The signed-in user (`id`, `email`, `display_name`, `created_at`, `onboarding_completed`); PATCH sets `display_name` and/or `onboarding_completed`. |
| `DELETE /api/v1/users/me` | Implemented (M4) | `{password}`; deletes the account and everything that belongs to it (events, profile, preferences, playlists, sessions). `204`; `403` for a wrong password. |
| `GET /api/v1/users/me/export` | Implemented (M4) | All of the user's data as a JSON attachment: account (without the password hash), preferences, interactions, taste profile, playlists with tracks, sessions (without token hashes). |
| `GET /api/v1/users/me/preferences`, `PUT …` | Implemented (M4) | Declared preferences: `exploration_mode` (`familiar`, `balanced`, `explorer`, or null for automatic), `personalization_enabled`, favourite and excluded artists (ids) and genres (names), favourite moods (up to 8 mood keys). PUT replaces them and rebuilds the profile. 422 for unknown references or an artist/genre both preferred and excluded. |
| `GET /api/v1/users/me/taste-profile?include_embeddings=` | Implemented (M4; M3 logic) | Genre and artist affinities (strongest first), negative artists, listening statistics, exploration preference and discovery target, profile and model versions; optionally the 128-d embeddings. |
| `GET /api/v1/users/me/taste` | Implemented (M4) | Taste analytics for the "Your taste" page: a one-sentence overview, top genres and artists, 12 weekly trend points, emerging and fading genres (last 14 days against before, only with at least 10 plays on each side), 30-day discovery statistics. Anything that cannot be computed reliably is empty or null. |
| `POST /api/v1/interactions` | Implemented (M4; M3 logic) | Record 1–500 events (`play`, `complete`, `replay`, `skip` with `position_ms`, `like`, `unlike`, `dislike`, `undislike`, `save`, `unsave`, `playlist_add`) for the signed-in user; `occurred_at` must carry a UTC offset and not be in the future. Idempotent per `client_event_id`. Rebuilds the taste profile and returns it with `recorded` and `duplicates`. 422 for unknown tracks. |
| `GET /api/v1/interactions/history?limit=&before=&event_type=` | Implemented (M4) | Event history with track summaries, newest first, paged with `before` / `next_before`; `event_type` is repeatable. |
| `GET /api/v1/interactions/state?track_id=` | Implemented (M4) | Current like / dislike / save state of 1–200 tracks (repeat `track_id`). |
| `GET /api/v1/recommendations/for-you?limit=&exploration=` | Implemented (M4; M3 engine) | The personalized mix: hybrid ranking over six candidate sources, MMR, artist cap 2, familiar/discovery balance from `exploration` (overrides the user's mode for this request). Cold-start users get a popularity or declared-taste mix. |
| `GET /api/v1/recommendations/hidden-gems?limit=` | Implemented (M4) | The personalized pipeline restricted to tracks below the 55th popularity percentile, with an 80% discovery target and at most one track per artist. |
| `GET /api/v1/recommendations/surprise` | Implemented (M4) | One track from an artist the user has never played, drawn at random (CSPRNG) from the 10 best explorer-mode discoveries. |
| `GET /api/v1/recommendations/because-you-listened?seeds=&limit=` | Implemented (M4) | For the user's 1–5 strongest recent tracks: what listeners of that track also play (item-item neighbours), else its content neighbours; unheard tracks only. Empty when personalization is off. |
| `GET /api/v1/recommendations/moods` | Implemented (M4) | The eight mood mixes (key, title, description, genres). |
| `GET /api/v1/recommendations/mood/{mood}?limit=&exclude=` | Implemented (M4) | A mood mix: tracks tagged with the mood's genres (affinity ≥ 0.25) whose AcousticBrainz tempo and danceability fit the recipe, ranked by genre fit, popularity and (signed in) taste similarity; heard tracks are skipped for signed-in users. `exclude` (repeatable, up to 100 ids) gives a fresh mix on regenerate. Public; personalized when signed in. 404 for unknown moods. |
| `GET /api/v1/playlists`, `POST …` | Implemented (M4) | The user's playlists (summaries with track count, duration and up to four artwork URLs). POST `{name, description?, track_ids?, generator?}`: manual, or generated from `for_you`, `mood`, `hidden_gems`, `genre` or `artist_radio` (5–100 tracks); explicit `track_ids` win over the generator, which is kept for regenerate. At most 200 playlists of 500 tracks. |
| `GET /api/v1/playlists/{id}`, `PATCH …`, `DELETE …` | Implemented (M4) | Detail with tracks in order; rename / describe; delete. Another user's playlist is a `404`. |
| `POST /api/v1/playlists/{id}/tracks`, `DELETE …/tracks/{track_id}` | Implemented (M4) | Add tracks (duplicates ignored; recorded as `playlist_add` feedback) or remove one. |
| `PUT /api/v1/playlists/{id}/tracks/order` | Implemented (M4) | `{track_ids}`: the new order; must be exactly the playlist's tracks. |
| `POST /api/v1/playlists/{id}/regenerate` | Implemented (M4) | Generated playlists only: replace the tracks with a fresh set from the same generator, leaving out the current ones. |
| `GET /api/v1/playlists/{id}/suggestions?limit=` | Implemented (M4) | Tracks that fit the playlist: nearest neighbours of its mean content embedding, re-ranked with popularity. |
| `GET /api/v1/integrations` | Implemented (M5) | Every provider (ListenBrainz, Spotify, YouTube, MusicBrainz): auth kind, capabilities, whether it is configured here, and the user's connection (status, account name, last import). Never tokens. |
| `POST /api/v1/integrations/{provider}/connect` | Implemented (M5) | `{token}`: connect a token-based provider (ListenBrainz). `422` if the provider rejects the token, `503` if token encryption is not configured. |
| `GET /api/v1/integrations/{provider}/authorize` | Implemented (M5) | `{url}`: the provider's sign-in page (OAuth with PKCE and a single-use `state`). |
| `GET /api/v1/integrations/{provider}/callback` | Implemented (M5) | Where the provider sends the browser back; finishes connecting and redirects to `/settings?integration=…&status=connected\|cancelled\|error`. |
| `DELETE /api/v1/integrations/{provider}?delete_imported=` | Implemented (M5) | Disconnect: revoke where the provider supports it, delete the tokens, optionally delete the history imported from it. `204`. |
| `POST /api/v1/integrations/{provider}/import` | Implemented (M5) | `{consent: true}` required (`422` otherwise). Imports listening history or library data as events (`source` = provider), matched to the catalogue by MBID, ISRC or exact artist and title; incremental and idempotent. Returns the run's counts. |
| `GET /api/v1/integrations/imports` | Implemented (M5) | The user's last 20 import runs. |
| `GET /api/v1/integrations/musicbrainz/search?q=&limit=` | Implemented (M5) | Recordings on MusicBrainz (1 request per second app-wide), with `track_id` when the catalogue has them. |
| `POST /api/v1/playlists/{id}/export` | Implemented (M5) | `{provider}`: create or update the playlist on a connected provider (private). Retry-safe; returns exported and unmatched counts and the remote URL. `409` not connected or reconnect needed, `429` rate limit or quota, `502` provider failure. |
| `GET /api/v1/playlists/{id}/exports` | Implemented (M5) | The playlist's exports, one per provider. |
| `POST /api/v1/recommendations/custom` | Implemented (M6) | `{prompt, limit?, exploration_level?, exclude_previously_heard?, exclude?}`: a playlist from a prompt (spec §9, FR-016). Returns the recommendations with evidence-based reasons, `interpretation` (genres, moods, artists, exclusions, tempo, energy, era, popularity, exploration, ignored words, summary) and `personalized`. Public; personalized and logged when signed in. `422` (`prompt_not_understood`, with the ignored words) when nothing matches the catalogue. |
| All other endpoints above  | Planned     | Playlist export to file formats and further integrations: later milestones (see ROADMAP.md). |

**Milestone 6 additions to existing endpoints.**

- Every request may send `X-Timezone` (an IANA name such as `Europe/Berlin`); invalid values are
  ignored. The web app sends the browser's zone.
- `GET /recommendations/for-you` responses carry `context` (session evidence and the weights
  applied) and, when the user is in a running experiment, `experiment` and `variant`. For-you,
  hidden gems, surprise, signed-in mood mixes and prompt playlists are logged with their
  `request_id` (`recommendation_requests`, `recommendation_logs`).
- `POST /interactions` events accept an optional `request_id`: the response the feedback was
  given on, used to measure experiments.
- Playlist generators accept `{"collection": "custom", "prompt": ..., "exploration_level": ...}`.
- `GET /users/me/export` includes `recommendations_shown` (the logged responses and their items).

**Authentication.** Every `/users/me/…`, `/interactions…`, `/playlists…` and personalized
recommendation route requires a session (`401` otherwise); catalogue, mood and non-personal
recommendation routes are public. Sessions are opaque tokens in an `HttpOnly`, `SameSite=Lax`
cookie (`tastify_session`, `Secure` outside local development), stored only as SHA-256 hashes,
valid for 30 days and extended while in use. State-changing requests whose `Origin` is not an
allowed origin are rejected with `403` (CSRF defence). Details:
[ADR-017](ADR/ADR-017-authentication-and-user-application.md).

The browser never calls the API across origins: the Next.js server proxies `/api/v1/*` to the
backend (`frontend/src/proxy.ts`, `API_PROXY_TARGET`), so the session cookie is first-party.

When the backend is running, the interactive documentation is at <http://localhost:8000/docs> and the
OpenAPI schema is at <http://localhost:8000/api/v1/openapi.json>.

### Conventions

These follow from the database and security rules in this specification:

- All routes are versioned under `/api/v1`.
- Resource identifiers are UUIDs. Timestamps are ISO 8601 in UTC.
- Request and response bodies are Pydantic schemas (`backend/app/schemas/`). The frontend mirrors them
  in `frontend/src/types/`.
- Errors use FastAPI's `{"detail": ...}` shape with the appropriate HTTP status code.
