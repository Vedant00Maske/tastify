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
| `POST /api/v1/users` | Implemented (M3, development only) | Create a user. |
| `GET /api/v1/users/{user_id}` | Implemented (M3, development only) | The user. 404 if unknown. |
| `POST /api/v1/users/{user_id}/interactions` | Implemented (M3, development only) | Record 1–500 events (`play`, `complete`, `replay`, `skip` with `position_ms`, `like`, `unlike`, `dislike`, `undislike`, `save`, `unsave`, `playlist_add`); `occurred_at` must carry a UTC offset and not be in the future. Idempotent per `client_event_id`. Rebuilds the taste profile and returns it with `recorded` and `duplicates` counts. 422 for unknown tracks. |
| `GET /api/v1/users/{user_id}/interactions?limit=&before=` | Implemented (M3, development only) | Event history, newest first, paged with `before` / `next_before`. |
| `GET /api/v1/users/{user_id}/preferences`, `PUT …/preferences` | Implemented (M3, development only) | Declared preferences: `exploration_mode` (`familiar`, `balanced`, `explorer`, or null for automatic), `personalization_enabled`, favourite and excluded artists (ids) and genres (names, case-insensitive). PUT replaces them and rebuilds the profile. 422 for unknown references or an artist/genre both preferred and excluded. |
| `GET /api/v1/users/{user_id}/taste-profile?include_embeddings=` | Implemented (M3, development only) | Genre and artist affinities, negative artists, listening statistics, exploration preference and discovery target, profile and model versions; optionally the 128-d long- and short-term embeddings. |
| `GET /api/v1/users/{user_id}/recommendations?limit=&exploration=` | Implemented (M3, development only) | The personalized mix ("for you", spec `GET /recommendations/for-you`): hybrid ranking over six candidate sources, MMR, artist cap 2, familiar/discovery balance from `exploration` (overrides the user's mode for this request). Cold-start users get a popularity or declared-taste mix. |
| All other endpoints above  | Planned     | Delivered in later milestones (see ROADMAP.md).                                                           |

**Development-only user API.** Milestone 4 adds authentication. Until then, the `/users/{user_id}/…`
routes take the user id in the path and are served only when `ENVIRONMENT` is `local` or `test`
(or `DEV_USER_API=true`); elsewhere they return `404`. Milestone 4 replaces them with
`/users/me/…` and `/recommendations/for-you` behind authentication and ownership checks (spec §12.3).

When the backend is running, the interactive documentation is at <http://localhost:8000/docs> and the
OpenAPI schema is at <http://localhost:8000/api/v1/openapi.json>.

### Conventions

These follow from the database and security rules in this specification:

- All routes are versioned under `/api/v1`.
- Resource identifiers are UUIDs. Timestamps are ISO 8601 in UTC.
- Request and response bodies are Pydantic schemas (`backend/app/schemas/`). The frontend mirrors them
  in `frontend/src/types/`.
- Errors use FastAPI's `{"detail": ...}` shape with the appropriate HTTP status code.
