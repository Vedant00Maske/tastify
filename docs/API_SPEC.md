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
| All other endpoints above  | Planned     | Delivered in later milestones (see ROADMAP.md).                                                           |

When the backend is running, the interactive documentation is at <http://localhost:8000/docs> and the
OpenAPI schema is at <http://localhost:8000/api/v1/openapi.json>.

### Conventions

These follow from the database and security rules in this specification:

- All routes are versioned under `/api/v1`.
- Resource identifiers are UUIDs. Timestamps are ISO 8601 in UTC.
- Request and response bodies are Pydantic schemas (`backend/app/schemas/`). The frontend mirrors them
  in `frontend/src/types/`.
- Errors use FastAPI's `{"detail": ...}` shape with the appropriate HTTP status code.
