# SONIQUEO
## Product Requirements & Engineering Design Specification

**Document Version:** 1.0  
**Status:** Approved for initial development planning  
**Product Type:** Music Discovery & Recommendation Platform  
**Architecture:** Modular Monolith  
**Initial Release:** Web Application  
**Development Approach:** Product-oriented, test-driven, iterative development

---

# 1. Executive Summary

SONIQUEO is a personalized music discovery and playlist generation platform that learns individual musical preferences and recommends songs based on listening history, user interactions, musical characteristics, moods, genres and discovery preferences.

The platform will integrate with music services such as Spotify, YouTube and open music ecosystems wherever supported APIs and usage permissions allow.

Unlike a conventional playlist generator, SONIQUEO will maintain its own recommendation intelligence. External platforms will primarily act as music metadata, user-data and playlist-export providers.

The system will combine:

- Collaborative filtering.
- Content-based filtering.
- Hybrid recommendation models.
- Music and user embeddings.
- Personalized ranking algorithms.
- Diversity-aware recommendation.
- Feedback-driven personalization.
- Context-aware playlist generation.

The product must be designed for real users, with proper authentication, privacy, scalable data processing, testing, observability and deployment practices.

## 1.1 Product Vision

Build an intelligent music discovery platform that understands not just what users listen to, but what they enjoy, why they enjoy it and what they might discover next.

## 1.2 Core Objectives

1. Build personalized music recommendations.
2. Generate playlists across multiple categories.
3. Learn continuously from user interactions.
4. Discover relevant music outside existing listening patterns.
5. Support multiple music platforms.
6. Provide explainable and configurable recommendations.
7. Build a production-ready application with measurable recommendation quality.

---

# 2. Product Requirements Document (PRD)

## 2.1 Target Users

- Music enthusiasts who want personalized discovery.
- Users who frequently explore new artists and genres.
- Users who want mood-based playlists.
- Users who use multiple music platforms.
- Users who want better control over recommendation diversity.

## 2.2 Core Features

### A. User Authentication

- Registration and login.
- OAuth authentication where supported.
- Secure session management.
- Account disconnection and deletion.
- User consent for external data imports.

### B. Onboarding and Taste Profiling

Users should be able to specify:

- Favourite genres.
- Favourite artists.
- Favourite tracks.
- Preferred languages.
- Preferred moods.
- Music they dislike.
- Desired familiarity versus exploration.

The system creates an initial user taste profile.

### C. Personalized Discovery

Generate recommendations based on:

- Listening history.
- Liked tracks.
- Saved tracks.
- Skipped tracks.
- Repeated listening.
- Artist preferences.
- Genre preferences.
- Similar user behaviour.
- Musical characteristics.

### D. Recommendation Categories

1. For You.
2. Mood Mix.
3. Artist Radio.
4. Genre Explorer.
5. Hidden Gems.
6. Activity-based Playlists.
7. Recently Discovered.
8. Similar to Your Favourite Tracks.
9. Surprise Me.
10. Custom AI Playlist.

### E. Playlist Management

- Generate playlists.
- Add and remove tracks.
- Reorder tracks.
- Regenerate recommendations.
- Save playlists.
- Export playlists to connected providers.
- Maintain playlist history.

### F. Feedback Collection

Supported events:

- PLAY
- COMPLETE
- SKIP
- LIKE
- DISLIKE
- SAVE
- REPLAY
- ADD_TO_PLAYLIST
- REMOVE_FROM_PLAYLIST

Events must be timestamped and associated with the user and relevant track.

### G. Taste Evolution

The application should display:

- Most listened genres.
- Favourite artists.
- Emerging interests.
- Listening patterns over time.
- Discovery statistics.
- Changes in taste profile.

---

# 3. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-001 | User registration and authentication | P0 |
| FR-002 | Music preference onboarding | P0 |
| FR-003 | Music catalogue ingestion | P0 |
| FR-004 | Track search | P0 |
| FR-005 | Content-based recommendations | P0 |
| FR-006 | User interaction tracking | P0 |
| FR-007 | Personalized playlist generation | P0 |
| FR-008 | Feedback-driven personalization | P0 |
| FR-009 | Recommendation ranking | P0 |
| FR-010 | Diversity-aware recommendations | P1 |
| FR-011 | Collaborative filtering | P1 |
| FR-012 | Spotify integration | P1 |
| FR-013 | YouTube integration | P1 |
| FR-014 | ListenBrainz integration | P1 |
| FR-015 | Taste evolution dashboard | P1 |
| FR-016 | Natural-language playlist generation | P2 |
| FR-017 | Browser extension | P2 |

P0 means required for the first usable release.

P1 means the next major release.

P2 means an advanced feature.

---

# 4. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | Recommendation API target p95 latency below 500 ms for cached and precomputed recommendations |
| Availability | Initial production target of 99.5% monthly availability |
| Security | Secure authentication and encrypted credentials |
| Scalability | Support horizontal application scaling |
| Maintainability | Modular architecture and documented interfaces |
| Reliability | Retry-safe asynchronous processing |
| Observability | Structured logs, metrics and error tracking |
| Privacy | Explicit consent and user-controlled data deletion |
| Testability | Unit, integration, contract and end-to-end tests |
| Compatibility | Responsive web application |
| Accessibility | Keyboard navigation and accessible UI components |

These are initial engineering targets, not measured performance guarantees.

---

# 5. High-Level Design (HLD)

## 5.1 Architectural Style

SONIQUEO will initially use a modular monolith.

Reasoning:

- Easier initial development.
- Simpler deployment.
- Lower infrastructure costs.
- Clear separation of responsibilities.
- Easier local debugging.
- Ability to extract individual services later.

We will avoid premature microservices.

## 5.2 System Components

### Presentation Layer
Technology: Next.js, React, TypeScript.

Responsibilities:
- Authentication interfaces.
- Onboarding.
- Recommendation dashboard.
- Playlist management.
- User preferences.
- Interaction collection.

### API Layer
Technology: FastAPI.

Responsibilities:
- Request validation.
- Authentication and authorization.
- API routing.
- Rate limiting.
- Response serialization.
- Coordination between business services.

### User Domain

Responsibilities:
- User accounts.
- User preferences.
- Taste profiles.
- External account connections.
- User interaction history.

### Music Catalogue Domain

Responsibilities:
- Track metadata.
- Artist information.
- Genre classification.
- External provider identifiers.
- Music feature management.
- Catalogue deduplication.

### Recommendation Domain

Responsibilities:
- Candidate generation.
- Candidate filtering.
- Recommendation ranking.
- Diversity re-ranking.
- Recommendation explanations.

### Playlist Domain

Responsibilities:
- Playlist creation.
- Playlist editing.
- Track ordering.
- Playlist persistence.
- External playlist export.

### Integration Domain

Responsibilities:
- Provider authentication.
- Metadata retrieval.
- User-data imports.
- Playlist export.
- Provider-specific rate limits.
- Error handling and retries.

### ML Domain

Responsibilities:
- Data preprocessing.
- Feature engineering.
- Model training.
- Embedding generation.
- Model evaluation.
- Model versioning.
- Inference.

## 5.3 HLD Data Flow

1. User registers.
2. User connects a supported music provider or selects onboarding preferences.
3. The integration layer retrieves permitted information.
4. Data is normalized into the internal music catalogue.
5. Interaction events are recorded.
6. Feature engineering creates user and track representations.
7. The recommendation engine generates candidates.
8. The ranking engine scores candidates.
9. The diversity layer produces the final recommendation list.
10. The frontend displays recommendations.
11. User feedback is collected.
12. The feedback updates future recommendations.

## 5.4 Proposed Infrastructure

| Component | Technology |
|---|---|
| Frontend | Next.js |
| Backend | FastAPI |
| Primary database | PostgreSQL |
| Vector search | pgvector |
| Cache | Redis |
| Background jobs | Celery |
| Task broker | Redis |
| ML framework | PyTorch |
| Classical ML | scikit-learn |
| Data processing | pandas, NumPy |
| Experiment tracking | MLflow |
| Containerization | Docker |
| CI/CD | GitHub Actions |
| Monitoring | Prometheus and Grafana |
| Error tracking | Sentry |
| Object storage | S3-compatible storage |

---

# 6. Low-Level Design (LLD)

## 6.1 Design Principles

We will follow:

- SOLID principles.
- Dependency inversion.
- Repository pattern.
- Strategy pattern.
- Factory pattern where appropriate.
- Dependency injection.
- Domain-driven module boundaries.
- Separation of business logic and infrastructure.

## 6.2 Main Domain Entities

### User

Attributes:
- id
- email
- password_hash (only for local authentication)
- status
- created_at
- updated_at

### UserPreference

Attributes:
- id
- user_id
- preferred_genres
- preferred_artists
- preferred_languages
- preferred_moods
- exploration_level
- excluded_artists

### Track

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

### Artist

Attributes:
- id
- name
- external_identifiers
- metadata

### TrackFeatures

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

### UserInteraction

Attributes:
- id
- user_id
- track_id
- event_type
- event_timestamp
- session_id
- source
- metadata

### Playlist

Attributes:
- id
- user_id
- name
- category
- description
- created_at
- updated_at

### PlaylistTrack

Attributes:
- playlist_id
- track_id
- position
- added_at

### RecommendationLog

Attributes:
- id
- user_id
- track_id
- recommendation_category
- ranking_score
- model_version
- request_id
- created_at

## 6.3 Database Relationships

- User 1:N UserPreference (or one active preference record).
- User 1:N UserInteraction.
- User 1:N Playlist.
- User N:M Track through UserInteraction.
- Artist 1:N Track.
- Track 1:N TrackFeatures versions.
- Playlist N:M Track through PlaylistTrack.
- User 1:N RecommendationLog.

## 6.4 Database Design Rules

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

## 6.5 Required Indexes

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

## 6.6 Main Application Classes

### UserProfileService

- get_profile()
- update_preferences()
- update_taste_profile()
- get_user_history()

### MusicCatalogService

- get_track()
- search_tracks()
- get_artist()
- resolve_external_track()

### InteractionService

- record_event()
- validate_event()
- get_interaction_history()
- aggregate_interactions()

### CandidateGenerator

- generate_content_candidates()
- generate_collaborative_candidates()
- generate_popularity_candidates()
- merge_candidates()

### RecommendationRanker

- calculate_content_score()
- calculate_collaborative_score()
- calculate_novelty_score()
- calculate_mood_score()
- calculate_final_score()

### DiversityReranker

- remove_duplicates()
- apply_artist_constraints()
- calculate_mmr()
- generate_diverse_results()

### RecommendationService

- recommend()
- recommend_by_mood()
- recommend_by_artist()
- recommend_by_genre()
- recommend_hidden_gems()

### PlaylistService

- create_playlist()
- update_playlist()
- add_track()
- remove_track()
- reorder_tracks()
- export_playlist()

### ProviderIntegrationService

- authenticate_provider()
- import_user_data()
- search_provider_catalogue()
- export_playlist()
- refresh_access_token()

---

# 7. Data Engineering and ML Pipeline

The ML pipeline must remain independent of the web application's business logic.

## 7.1 Data Pipeline Stages

### Stage 1: Data Ingestion

Sources:
- User interactions.
- MusicBrainz.
- ListenBrainz.
- Spotify where permitted.
- YouTube where permitted.
- Licensed or open research datasets.

### Stage 2: Data Validation

Validate:
- Missing identifiers.
- Invalid timestamps.
- Duplicate records.
- Invalid metadata.
- Out-of-range feature values.
- Incorrect data types.

### Stage 3: Cleaning

- Deduplicate tracks.
- Resolve artist identifiers.
- Standardize text.
- Normalize genres.
- Remove invalid records.
- Handle missing features.

### Stage 4: Entity Resolution

Different providers may identify the same track differently.

Use:
- ISRC where available.
- Provider-specific IDs.
- Artist and track names.
- Album and release metadata.
- Duration comparison.

Never merge tracks based on title alone.

### Stage 5: Feature Engineering

Track features:
- Genre.
- Artist.
- Album.
- Tempo, if available.
- Energy, if available.
- Mood representation.
- Audio/text embeddings where licensed.

User features:
- Genre affinity.
- Artist affinity.
- Recent listening.
- Long-term listening.
- Skip frequency.
- Replay frequency.
- Discovery preference.

### Stage 6: Feature Storage

- PostgreSQL for structured features.
- pgvector for embeddings.
- Redis for frequently used online features.
- Object storage for permitted training artifacts.

### Stage 7: Model Training

Train and evaluate individual recommendation approaches.

### Stage 8: Model Evaluation

Compare against a popularity baseline and previous model versions.

### Stage 9: Model Registration

Register:
- Model version.
- Training dataset version.
- Hyperparameters.
- Evaluation metrics.
- Feature schema.
- Training timestamp.

### Stage 10: Model Serving

Expose recommendations through the backend recommendation service.

---

# 8. Recommendation Engine Design

## 8.1 Recommendation Approaches

### A. Popularity Baseline

Recommend popular tracks.

Purpose:
- Cold-start fallback.
- Baseline comparison.
- General discovery.

### B. Content-Based Filtering

Represent tracks through their metadata and available features.

Use:
- TF-IDF for textual metadata.
- Categorical encoding.
- Feature normalization.
- Embeddings.
- Cosine similarity.

### C. Collaborative Filtering

Use user-item interactions.

Initial approaches:
- Item-item similarity.
- Implicit-feedback matrix factorization.
- ALS or equivalent techniques.

Later:
- Neural collaborative filtering.

### D. Hybrid Recommendation

Combine content-based, collaborative and popularity signals.

Example:

FinalScore =
w1(ContentScore) +
w2(CollaborativeScore) +
w3(NoveltyScore) +
w4(MoodScore) +
w5(FamiliarityScore)

Weights must be calibrated and normalized before combination.

### E. Diversity Re-ranking

Use Maximal Marginal Relevance:

MMR(t) = λ Rel(t,u) - (1-λ) max Sim(t,s)

Where:
- Rel measures user relevance.
- Sim measures similarity to already-selected tracks.
- λ controls relevance versus diversity.

## 8.2 Candidate Generation

The candidate generation stage should retrieve a larger collection than the final playlist size.

Example:
- Retrieve 300–500 candidates.
- Filter unavailable and unwanted tracks.
- Rank candidates.
- Apply diversity.
- Return the final 20–50 tracks.

These are initial experimental values, not fixed production limits.

## 8.3 Cold-Start Handling

New users:
- Onboarding preferences.
- Favourite artist selection.
- Favourite genre selection.
- Popularity-based recommendations.
- Content-based similarity.

New tracks:
- Metadata-based representation.
- Content embeddings.
- Genre and artist similarity.
- Exploration sampling.

## 8.4 User Taste Profile

Maintain two representations:

**Long-term profile**
- Stable genre preferences.
- Favourite artists.
- Historical interaction patterns.

**Short-term profile**
- Current mood preferences.
- Recent listening.
- Current session intent.
- Temporary discovery interests.

The short-term profile should not permanently overwrite long-term preferences.

## 8.5 Feedback Weighting

Initial event weights can be configurable:

| Event | Initial interpretation |
|---|---|
| Like | Strong positive |
| Save | Strong positive |
| Complete | Positive |
| Replay | Positive |
| Add to playlist | Strong positive |
| Skip very early | Negative |
| Dislike | Strong negative |

Do not treat every skip as a dislike. Users may skip for reasons unrelated to musical preference.

Weights must be tuned through experimentation.

---

# 9. Recommendation API Design

Base URL: `/api/v1`

## Authentication

POST `/auth/register`

POST `/auth/login`

POST `/auth/logout`

GET `/users/me`

## Preferences

GET `/users/me/preferences`

PUT `/users/me/preferences`

## Music Catalogue

GET `/tracks/search?q=`

GET `/tracks/{track_id}`

GET `/artists/{artist_id}`

## Recommendations

GET `/recommendations/for-you`

GET `/recommendations/mood/{mood}`

GET `/recommendations/artist/{artist_id}`

GET `/recommendations/genre/{genre}`

GET `/recommendations/hidden-gems`

POST `/recommendations/custom`

## Interactions

POST `/interactions`

GET `/interactions/history`

## Playlists

POST `/playlists`

GET `/playlists`

GET `/playlists/{playlist_id}`

PATCH `/playlists/{playlist_id}`

POST `/playlists/{playlist_id}/tracks`

DELETE `/playlists/{playlist_id}/tracks/{track_id}`

POST `/playlists/{playlist_id}/export`

## Integrations

GET `/integrations`

GET `/integrations/{provider}/authorize`

GET `/integrations/{provider}/callback`

DELETE `/integrations/{provider}`

All endpoints must enforce authorization, input validation and appropriate rate limits.

## Example Recommendation Request

POST `/api/v1/recommendations/custom`

Request:

{
  "prompt": "Indie rock with electronic influence",
  "limit": 25,
  "exploration_level": 0.7,
  "exclude_previously_heard": true
}

Response:

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

Scores and reasons must be based on actual model outputs and recorded evidence.

---

# 10. Music Platform Integration Design

## 10.1 Provider Abstraction

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

## 10.2 Spotify

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

## 10.3 YouTube

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

## 10.4 Open Music Ecosystem

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

# 11. Testing Strategy

Testing is a first-class development requirement.

## 11.1 Unit Testing

Tools:
- pytest.
- pytest-cov.
- Vitest.

Test:
- User services.
- Repository methods.
- Feature engineering.
- Recommendation scoring.
- Candidate filtering.
- Diversity algorithms.
- Playlist operations.

## 11.2 Integration Testing

Test:
- Backend and PostgreSQL.
- Backend and Redis.
- Repository and database.
- Recommendation service and ML models.
- Background processing.
- Provider adapters.

Use isolated test databases and mock external services where appropriate.

## 11.3 ML Testing

### Data Tests
- Missing value checks.
- Duplicate detection.
- Feature range validation.
- Data leakage checks.
- Schema compatibility.

### Model Tests
- Deterministic inference where expected.
- Output shape validation.
- Score normalization.
- Cold-start behaviour.
- Model version compatibility.

### Recommendation Tests
- Precision@K.
- Recall@K.
- NDCG@K.
- MAP@K.
- Catalog coverage.
- Diversity.
- Novelty.

## 11.4 API Contract Testing

Validate:
- Request schemas.
- Response schemas.
- Authentication failures.
- Authorization failures.
- Pagination.
- Rate limiting.
- Invalid parameters.
- Provider failures.

## 11.5 End-to-End Testing

Tools:
- Playwright.

Test user journeys:

1. Registration.
2. Login.
3. Onboarding.
4. Connecting a music provider.
5. Generating recommendations.
6. Liking and skipping tracks.
7. Generating a playlist.
8. Editing a playlist.
9. Exporting a playlist.
10. Disconnecting a provider.
11. Deleting an account.

## 11.6 Security Testing

Test:
- Broken access control.
- SQL injection.
- Cross-site scripting.
- CSRF where applicable.
- OAuth state validation.
- Token leakage.
- Rate-limit bypass.
- Insecure direct object references.
- Unauthorized playlist modifications.

## 11.7 Initial Quality Gates

- All critical unit and integration tests pass.
- No unresolved critical security vulnerabilities.
- API contracts are validated.
- Database migrations work from a clean database.
- ML evaluation results are recorded.
- No user can access another user's private playlists.
- No provider credential is committed to source control.

---

# 12. Security and Privacy Architecture

## 12.1 Authentication

Use OAuth 2.0/OIDC where supported.

For local authentication:
- Argon2id password hashing.
- Secure session cookies.
- Session expiration.
- Refresh and revocation controls.

## 12.2 External Credentials

- Encrypt tokens at rest.
- Never expose tokens to the frontend.
- Never log access tokens.
- Request minimum necessary scopes.
- Support token revocation.
- Separate user tokens from application credentials.

## 12.3 Authorization

Use user-level ownership checks for:
- Playlists.
- Preferences.
- Interactions.
- Personal listening history.
- External connections.

## 12.4 Privacy

Provide:
- Clear consent.
- Data export.
- Account deletion.
- Provider disconnection.
- Data retention controls.
- Personalization opt-out.

Do not collect precise location or unnecessary device information for recommendations.

---

# 13. Data Structures and Algorithm Selection

| Data structure | Application | Complexity benefit |
|---|---|---|
| HashMap | Track lookup | O(1) average |
| HashSet | Deduplication | O(1) average |
| Heap | Top-K candidates | O(N log K) |
| Sparse Matrix | User-item interactions | Memory efficient |
| Graph | User-artist-track relationships | Relationship traversal |
| Vector Index | Similarity retrieval | Efficient approximate search |
| Queue | Background jobs | Asynchronous processing |
| LRU Cache | Recommendation caching | Fast repeated reads |

We will select structures based on measured workload rather than introducing them just to demonstrate knowledge of data structures.

---

# 14. Deployment Architecture

## Environments

1. Local development.
2. Automated testing.
3. Staging.
4. Production.

## Deployment Process

1. Developer creates a feature branch.
2. Pull request is opened.
3. Formatting and linting execute.
4. Unit tests execute.
5. Integration tests execute.
6. Security checks execute.
7. Docker image is built.
8. Staging deployment occurs.
9. Smoke tests execute.
10. Production deployment is approved.

## Containerization

Initial containers:

- frontend
- backend
- postgres
- redis
- worker

ML training can run as a separate job rather than requiring a continuously running training service.

## Database Management

- Version-controlled migrations.
- Automated backups.
- Restore testing.
- Connection pooling.
- Migration validation.

---

# 15. Monitoring and Observability

## Application Metrics

- Request count.
- Error rate.
- API latency.
- Database query latency.
- Cache hit rate.
- Background job failures.
- External provider failures.

## Recommendation Metrics

- Candidate generation time.
- Ranking latency.
- Number of candidates retrieved.
- Recommendation coverage.
- Recommendation diversity.
- Feedback conversion.
- Model version distribution.

## User Experience Metrics

- Playlist save rate.
- Recommendation acceptance.
- Track skip rate.
- Repeat listening.
- User retention.
- User satisfaction.

Monitor these in aggregate and respect user consent and privacy.

---

# 16. Development Roadmap

## Milestone 0 – Engineering Foundation

Tasks:
- Create GitHub repository.
- Define branching strategy.
- Create documentation.
- Establish coding standards.
- Configure CI.
- Create Docker development environment.
- Configure database migrations.

Acceptance criteria:
- Project runs locally.
- CI executes.
- Database migrations work.
- Documentation is version controlled.

## Milestone 1 – Data Foundation

Tasks:
- Define relational schema.
- Implement catalogue ingestion.
- Implement cleaning.
- Implement normalization.
- Implement entity resolution.
- Add interaction event ingestion.

Acceptance criteria:
- Valid catalogue records are stored.
- Duplicate records are handled.
- Data validation tests pass.
- Interaction events can be persisted.

## Milestone 2 – Recommendation V1

Tasks:
- Implement popularity baseline.
- Implement content-based filtering.
- Implement track similarity.
- Implement candidate generation.
- Implement basic ranking.
- Evaluate using offline datasets.

Acceptance criteria:
- Recommendations are returned through an API.
- Evaluation metrics are recorded.
- Baseline comparisons are documented.

## Milestone 3 – Hybrid Recommendation

Tasks:
- Implement collaborative filtering.
- Combine recommendation strategies.
- Implement diversity re-ranking.
- Implement cold-start fallback.
- Introduce model versioning.

Acceptance criteria:
- Multiple retrieval strategies operate independently.
- Hybrid ranking is reproducible.
- Recommendation quality is benchmarked.

## Milestone 4 – User Application

Tasks:
- Implement authentication.
- Build onboarding.
- Build dashboard.
- Build recommendation categories.
- Build playlist management.
- Implement feedback controls.

Acceptance criteria:
- Users can register and onboard.
- Recommendations are personalized.
- Feedback changes future recommendations.
- Users can create and manage playlists.

## Milestone 5 – External Integrations

Tasks:
- Implement provider abstraction.
- Integrate ListenBrainz.
- Integrate MusicBrainz.
- Implement Spotify adapter where permitted.
- Implement YouTube adapter.
- Implement playlist export.

Acceptance criteria:
- Provider-specific failures are isolated.
- Tokens are securely managed.
- Playlist export is retry-safe.
- Provider quotas are respected.

## Milestone 6 – Production Release

Tasks:
- Performance testing.
- Security testing.
- Load testing.
- Monitoring.
- Deployment.
- Backup and recovery.
- Privacy documentation.
- Beta testing.

Acceptance criteria:
- Production environment is available.
- Critical user journeys pass.
- No known critical security vulnerabilities.
- Monitoring and error reporting work.
- User data deletion works.

---

# 17. Proposed Initial Repository Structure

soniqueo/
│
├── frontend/
│   └── src/
│       ├── app/
│       ├── components/
│       ├── features/
│       │   ├── auth/
│       │   ├── discovery/
│       │   ├── playlists/
│       │   ├── taste-profile/
│       │   └── integrations/
│       ├── hooks/
│       ├── services/
│       └── types/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── core/
│   │   ├── domains/
│   │   │   ├── users/
│   │   │   ├── catalogue/
│   │   │   ├── interactions/
│   │   │   ├── recommendations/
│   │   │   ├── playlists/
│   │   │   └── integrations/
│   │   ├── repositories/
│   │   ├── schemas/
│   │   └── workers/
│   └── tests/
│
├── ml/
│   ├── data/
│   │   ├── ingestion/
│   │   ├── cleaning/
│   │   ├── normalization/
│   │   └── validation/
│   ├── features/
│   ├── embeddings/
│   ├── models/
│   │   ├── popularity/
│   │   ├── content_based/
│   │   ├── collaborative/
│   │   └── hybrid/
│   ├── ranking/
│   ├── evaluation/
│   ├── experiments/
│   └── inference/
│
├── infrastructure/
│   ├── docker/
│   ├── deployment/
│   └── monitoring/
│
├── docs/
│   ├── PRD.md
│   ├── HLD.md
│   ├── LLD.md
│   ├── DATABASE.md
│   ├── API_SPEC.md
│   ├── ML_PIPELINE.md
│   ├── TESTING.md
│   ├── SECURITY.md
│   ├── DEPLOYMENT.md
│   └── ADR/
│
├── scripts/
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md

---

# 18. Architecture Decision Records (ADR)

Every significant architectural choice must be documented.

Initial decisions:

| ADR | Decision |
|---|---|
| ADR-001 | Modular monolith instead of microservices |
| ADR-002 | FastAPI for backend |
| ADR-003 | PostgreSQL as primary database |
| ADR-004 | pgvector for initial vector retrieval |
| ADR-005 | Independent recommendation engine |
| ADR-006 | Provider abstraction for music integrations |
| ADR-007 | Immutable interaction event history |
| ADR-008 | Separate offline training and online inference |
| ADR-009 | Docker-based development and deployment |
| ADR-010 | Test-driven development for core business logic |

Every ADR must include:
- Context.
- Problem.
- Alternatives considered.
- Decision.
- Consequences.
- Date.
- Status.

---

# 19. Initial Product Release Scope

The first public beta must not attempt to implement every advanced feature.

The minimum useful release should contain:

1. User authentication.
2. Music catalogue.
3. Onboarding and preferences.
4. User taste profile.
5. Content-based recommendations.
6. Popularity fallback.
7. Recommendation categories.
8. Playlist generation.
9. Feedback collection.
10. Basic evaluation and monitoring.
11. At least one working external music integration.
12. Secure deployment.

Collaborative filtering, advanced neural ranking, multi-provider synchronization and natural-language playlist generation can follow as the data and product mature.

---

# 20. Definition of Done

A feature is not considered complete merely because it works on a developer's machine.

Every feature must have:

- Defined requirements.
- Documented interfaces.
- Implementation.
- Unit tests.
- Integration tests where applicable.
- Error handling.
- Input validation.
- Logging and monitoring where relevant.
- Security review.
- Updated documentation.
- Code review.
- Successful CI checks.

For ML features, add:
- Dataset provenance.
- Feature definitions.
- Reproducible experiments.
- Evaluation results.
- Model version.
- Known limitations.

---

# 21. Final Engineering Principles

The following principles govern the entire project:

1. Recommendation intelligence belongs to SONIQUEO, not external music platforms.
2. No provider-specific assumptions should leak into the core recommendation domain.
3. Every recommendation model must be evaluated against a baseline.
4. Every user interaction must have a clearly defined meaning.
5. Short-term interests must not automatically overwrite long-term taste.
6. Relevance and diversity must be balanced.
7. User data must be handled with explicit consent.
8. Security and testing are part of development, not final-stage activities.
9. Avoid premature optimization and unnecessary distributed architecture.
10. Prioritize measurable user value over algorithmic complexity.

## Final Product Goal

SONIQUEO should become a working, publicly accessible music discovery product that demonstrates end-to-end Machine Learning Engineering:

**Data Engineering → Feature Engineering → Model Development → Candidate Retrieval → Ranking → Evaluation → Backend Integration → Frontend → Deployment → Real User Feedback.**

The architecture must remain extensible enough to support new recommendation models, additional music platforms and increasing numbers of users without rewriting the core application.

**Document status: Initial engineering specification approved. Implementation begins with Milestone 0.**
