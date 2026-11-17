# TASTIFY — Database Design

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§6.2–6.5).
> This file is the maintained version: update it in the same pull request as the code it describes.

### 6.2 Main Domain Entities

#### User

Attributes:
- id
- email
- password_hash (only for local authentication)
- status
- created_at
- updated_at

#### UserPreference

Attributes:
- id
- user_id
- preferred_genres
- preferred_artists
- preferred_languages
- preferred_moods
- exploration_level
- excluded_artists

#### Track

Attributes:
- id
- title
- duration_ms
- release_date
- artist_id
- album_id
- isrc
- metadata_source
- created_at

#### Artist

Attributes:
- id
- name
- external_identifiers
- metadata

#### TrackFeatures

Attributes:
- track_id
- tempo
- energy
- danceability
- valence
- acousticness
- instrumentalness
- feature_source
- feature_version

Features are optional and must only be populated from permitted sources or our own models.

#### UserInteraction

Attributes:
- id
- user_id
- track_id
- event_type
- event_timestamp
- session_id
- source
- metadata

#### Playlist

Attributes:
- id
- user_id
- name
- category
- description
- created_at
- updated_at

#### PlaylistTrack

Attributes:
- playlist_id
- track_id
- position
- added_at

#### RecommendationLog

Attributes:
- id
- user_id
- track_id
- recommendation_category
- ranking_score
- model_version
- request_id
- created_at

### 6.3 Database Relationships

- User 1:N UserPreference (or one active preference record).
- User 1:N UserInteraction.
- User 1:N Playlist.
- User N:M Track through UserInteraction.
- Artist 1:N Track.
- Track 1:N TrackFeatures versions.
- Playlist N:M Track through PlaylistTrack.
- User 1:N RecommendationLog.

### 6.4 Database Design Rules

1. Use UUID primary keys.
2. Enforce foreign key constraints.
3. Add indexes to frequently queried fields.
4. Use unique constraints for provider identifiers.
5. Use database migrations.
6. Store timestamps in UTC.
7. Preserve immutable interaction events.
8. Separate raw events from aggregated features.
9. Avoid storing duplicate provider metadata unnecessarily.
10. Use JSONB only for genuinely variable metadata, not as a substitute for relational modelling.

### 6.5 Required Indexes

- users(email)
- tracks(isrc)
- tracks(artist_id)
- artists(name)
- user_interactions(user_id, event_timestamp)
- user_interactions(track_id, event_type)
- playlists(user_id, created_at)
- playlist_tracks(playlist_id, position)
- recommendation_logs(user_id, created_at)

Use composite indexes based on actual query plans after profiling.

---

## Implemented catalogue schema (Milestone 1)

ORM models: `backend/app/domains/catalogue/models.py`. Migration: `65ea8b207eac`.

```mermaid
erDiagram
    data_sources ||--o{ ingestion_jobs : "runs"
    ingestion_jobs ||--o{ ingestion_errors : "rejects"
    data_sources ||--o{ raw_records : "provided"
    artists ||--o{ tracks : "primary artist"
    albums ||--o{ tracks : "contains"
    artists ||--o{ albums : "primary artist"
    tracks ||--|{ track_artists : "credited"
    artists ||--o{ track_artists : "credited on"
    tracks ||--|{ track_external_ids : "identified by"
    artists ||--o{ artist_external_ids : "identified by"
    albums ||--o{ album_external_ids : "identified by"
    tracks ||--o{ track_genres : ""
    artists ||--o{ artist_genres : ""
    genres ||--o{ track_genres : ""
    genres ||--o{ artist_genres : ""
    genres ||--o{ genres : "parent"
    tracks ||--o{ track_features : "versioned features"
    tracks ||--o{ entity_match_candidates : "possible duplicate of"
```

| Table | Purpose and key rules |
| --- | --- |
| `data_sources` | One row per external source, with licence and `usage_restriction` (`none`, `non_commercial`, `research_only`). Referenced by every record below. |
| `ingestion_jobs` / `ingestion_errors` | One job per pipeline stage run (parameters, statistics, status). Errors are sampled at up to 200 per code per job. |
| `raw_records` | API payloads exactly as received (JSONB + SHA-256), unique per (source, entity type, external id). |
| `artists`, `albums`, `tracks` | Canonical entities. `normalized_name`/`normalized_title` carry trigram (GIN) indexes for search. `tracks.matching_key` (artist \| cleaned title) is indexed for candidate lookup. `tracks.isrc` holds the primary ISRC. Albums are works (MusicBrainz release groups), not editions. |
| `track_artists` | Full ordered credit ("A feat. B"). Position 0 is the primary artist. |
| `track_external_ids`, `artist_external_ids`, `album_external_ids` | Provider identifiers, **unique per (provider, external_id)**. `match_method` (`source`, `isrc`, `metadata`, `track_link`) and `confidence` explain each link. ISRCs are stored here with provider `isrc`. |
| `genres` | MusicBrainz genre vocabulary plus FMA genres, with an optional parent (FMA hierarchy). |
| `track_genres`, `artist_genres` | Genre votes normalized to weights that sum to 1 per (track, source, level). `level` is `recording` or `album`. |
| `track_features` | Audio features per (track, feature_source, feature_version). Unit-scale columns are CHECK-constrained to [0, 1]. |
| `entity_match_candidates` | Possible duplicates awaiting review (`pending`, `accepted`, `rejected`), with JSONB evidence signals. |

Design notes:

- Text enums are `CHECK` constraints rather than PostgreSQL enum types, so adding a value is a
  plain migration.
- JSONB is used only for raw payloads, job parameters/statistics and match evidence, which are
  genuinely variable (rule 10).
- Listening events from ListenBrainz are research data and are **not** stored here (see
  DATA_SOURCES.md, Privacy). TASTIFY's own `users` and `user_interactions` arrived with
  Milestone 3 (below).

## Implemented recommendation schema (Milestone 2)

ORM models: `backend/app/domains/recommendations/models.py`. Migration: `6ec567b027d8`. Design:
ADR-015.

```mermaid
erDiagram
    model_versions ||--o{ track_popularity : "publishes"
    model_versions ||--o{ track_embeddings : "publishes"
    model_versions ||--o{ artist_embeddings : "publishes"
    tracks ||--o{ track_popularity : ""
    tracks ||--o{ track_embeddings : ""
    artists ||--o{ artist_embeddings : ""
```

| Table | Purpose and key rules |
| --- | --- |
| `model_versions` | Registry of trained models: `model_type` (`popularity`, `content`), unique `version`, `status` (`active`, `retired`), JSONB `params`, `training_data` (window, row counts, input SHA-256s) and offline `metrics`. A partial unique index allows **one active version per type**. |
| `track_popularity` | Per (version, track): distinct listeners, plays, log-normalized `score` in [0, 1], recent listeners and `trending_score` (NULL when the trend is not reliable). Indexed by (version, score) and (version, trending_score). |
| `track_embeddings` | Per (version, track): `vector(128)`, L2-normalized. HNSW index (`m=16`, `ef_construction=64`, `vector_cosine_ops`). |
| `artist_embeddings` | Per (version, artist): `vector(128)` (popularity-weighted mean of the artist's track embeddings) and `track_count`. HNSW index as above. |

Publishing a version (`python -m tastify_ml recommend publish`) inserts its rows, activates it and
deletes the serving rows of retired versions in one transaction. Retired versions keep their
registry row, so their parameters and metrics stay auditable, while the vector indexes only hold
active vectors. Resetting the catalogue (`catalogue reset`) truncates these tables and retires every
version.

## Implemented user and personalization schema (Milestone 3)

ORM models: `backend/app/domains/users/models.py` and `backend/app/domains/recommendations/models.py`.
Migration: `a28199fd7847`. Design: ADR-016.

```mermaid
erDiagram
    users ||--o| user_preferences : "settings"
    users ||--o{ user_artist_preferences : "declares"
    users ||--o{ user_genre_preferences : "declares"
    users ||--o{ user_interactions : "events"
    users ||--o| user_taste_profiles : "derived"
    artists ||--o{ user_artist_preferences : ""
    genres ||--o{ user_genre_preferences : ""
    tracks ||--o{ user_interactions : ""
    model_versions ||--o{ user_taste_profiles : "content model used"
    model_versions ||--o{ track_cf_factors : "publishes"
    model_versions ||--o{ track_neighbours : "publishes"
    model_versions ||--o{ model_artifacts : "stores"
    tracks ||--o{ track_cf_factors : ""
    tracks ||--o{ track_neighbours : "track and neighbour"
```

| Table | Purpose and key rules |
| --- | --- |
| `users` | TASTIFY users: id, `status` (`active`, `deleted`), timestamps. Credentials arrive with authentication in Milestone 4. |
| `user_preferences` | One row per user: `exploration_mode` (`familiar`, `balanced`, `explorer`; NULL = derived from behaviour) and `personalization_enabled` (opt-out, spec §12.4). No row means defaults. |
| `user_artist_preferences`, `user_genre_preferences` | Declared favourite (`preferred`) or `excluded` artists and genres, one row each, validated by foreign keys. |
| `user_interactions` | **Immutable** events (rule 7): `event_type` (`play`, `complete`, `replay`, `skip`, `like`, `unlike`, `dislike`, `undislike`, `save`, `unsave`, `playlist_add`), `occurred_at` (client time), `received_at` (server time), `position_ms` (how far playback got, e.g. an early skip), `session_id`, `source`. Unique (`user_id`, `client_event_id`) makes retried batches idempotent. Indexed by (user, occurred_at) and (track, event_type). Tracks referenced by events cannot be deleted (RESTRICT); deleting a user deletes their events (CASCADE). |
| `user_taste_profiles` | Derived profile (rule 8: aggregated features apart from raw events), rebuilt from events whenever events or preferences change, and lazily when the content model or the profile configuration changes: long- and short-term embeddings (`vector(128)`), genre/artist/negative-artist affinities (JSONB maps of at most 50 entries, always read and written whole), known artists, content seeds, listening statistics, exploration preference, `profile_version` and the content model version used. |
| `track_cf_factors` | Collaborative (ALS) track factors, `vector(256)`, with the track's BM25 idf; HNSW index on the inner product (`vector_ip_ops`). Users' factors are never stored: they are solved from the user's events at request time. |
| `track_neighbours` | Item-item collaborative neighbours: (track, neighbour, similarity), up to 100 per track (bounded for storage). Read by track only, through the primary key. |
| `model_artifacts` | Per-version files (`gram`: the ALS Gram matrix; `ranker`, `ranker_cc0`: LambdaRank tree ensembles as JSON) with media type and SHA-256. Kept for retired versions, so a previous ranker can be inspected or restored. |

`model_versions.model_type` now also allows `collaborative` and `hybrid`. Publishing rules are
unchanged (one active version per type; serving rows of retired versions are deleted;
`track_cf_factors` and `track_neighbours` are serving tables). No research user's data or
factors enter these tables: only item-level aggregates (ADR-016, DATA_SOURCES.md).

---

## Migrations workflow

Implemented in Milestone 0. Alembic runs on the async SQLAlchemy engine. The configuration lives in
`backend/alembic.ini`, and `backend/alembic/env.py` reads `DATABASE_URL` from the application
settings, so credentials never appear in `alembic.ini`.

Constraint names follow the naming convention in `backend/app/core/database.py`, so autogenerated
migrations stay deterministic. Revision files are named `YYYYMMDD_HHMM_<revision>_<slug>.py` and are
linted and formatted with ruff automatically when generated.

### Adding a schema change

1. Add or change models in `app/domains/<domain>/models.py` (inheriting from `app.core.database.Base`),
   and make sure the module is imported in `alembic/env.py`.
2. Generate a revision: `alembic revision --autogenerate -m "add users table"`.
3. **Review it by hand.** Autogenerate does not detect everything: extensions, renames (they appear as
   drop + add), some server-default and enum changes, and data migrations all need manual edits.
4. Verify both directions: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
5. Commit the model change and its migration in the same pull request.

### Rules

- Never edit a migration that has been merged to `main`. Write a new one instead.
- Every migration implements `downgrade()`. If a change is truly irreversible, raise with an explanation.
- Migrations must not import application models; they describe the schema as it was at that revision.
- CI applies all migrations to an empty database, rolls them back to base, re-applies them, and runs
  `alembic check` to fail on any drift between models and migrations.

### Revisions

| Revision       | Description                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------ |
| `3f6c2a9d1b0e` | Enable the `vector` extension (pgvector). Needs a superuser, or the extension pre-installed on managed PostgreSQL. |
| `65ea8b207eac` | Catalogue schema (Milestone 1): provenance, canonical tracks/artists/albums, external ids, genres, features, match review; enables `pg_trgm`. |
| `6ec567b027d8` | Recommendation models (Milestone 2): model registry, track popularity, track and artist embeddings with HNSW indexes. |
| `a28199fd7847` | Users and hybrid models (Milestone 3): users, preferences, immutable interactions, taste profiles, collaborative factors (HNSW inner product) and neighbours, model artifacts; `model_type` allows `collaborative` and `hybrid`. Downgrade deletes those versions first. |

### Databases

| Database       | Used by                                     | Created by                                                      |
| -------------- | ------------------------------------------- | --------------------------------------------------------------- |
| `tastify`      | Local development                           | `POSTGRES_DB` in docker compose                                 |
| `tastify_test` | Integration tests (`pytest -m integration`) | `infrastructure/docker/postgres/init/` (in CI: the service container) |
