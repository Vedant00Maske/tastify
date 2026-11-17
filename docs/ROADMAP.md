# TASTIFY — Development Roadmap

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§16).
> This file is the maintained version: update it in the same pull request as the code it describes.

## Current roadmap (revised 2026-11-16)

This plan supersedes the milestone numbering of the original §16 below, which is kept for reference.

| Milestone | Scope | Status |
| --- | --- | --- |
| 0 – Engineering Foundation | Repository, tooling, CI, Docker, migrations, documentation | Done |
| 1 – Music Data Foundation | Data source selection, catalogue ingestion, cleaning, normalization, entity resolution, database design | Done |
| 2 – Recommendation Engine V1 | Popularity baseline, content-based recommendations, similarity search, offline evaluation | Done |
| 3 – Personalized Hybrid Recommendation | Taste profiles, collaborative filtering, embeddings, candidate generation, ranking, diversity | Done (pending review) |
| 4 – Complete User Application | Authentication, onboarding, discovery dashboard, playlists, feedback, personalized categories | Planned |
| 5 – Music Platform Integrations | ListenBrainz, MusicBrainz, Spotify and YouTube integrations, subject to API permissions | Planned |
| 6 – Advanced Recommendation Intelligence | Context-aware ranking, cold-start improvements, natural-language playlists, experimentation, optimization | Planned |
| 7 – Production Hardening | Security audits, performance, scalability, observability, deployment, data recovery | Planned |
| 8 – Public Beta and Growth | Real users, feedback collection, A/B testing, model improvement, product analytics | Planned |

### Milestone 1 deliverables

Acceptance criterion: records from multiple sources can be ingested, and a unified track record can
be retrieved without depending on a specific provider.

- [x] Data sources selected, with provenance and licensing documented (DATA_SOURCES.md, ADR-013)
- [x] Normalized relational schema: canonical tracks/artists/albums, external ids, genres,
      features, provenance, match review (DATABASE.md, migration `65ea8b207eac`)
- [x] Entity resolution logic with an explicit policy and review queue (ADR-014)
- [x] Automated ingestion scripts: `python -m tastify_ml download` and `catalogue <stage>`
- [x] Reproducible cleaning and normalization pipeline (checksummed raw inputs, idempotent stages)
- [x] Data quality checks and report (`catalogue quality`, docs/reports/data-quality.md)
- [x] Provider-independent catalogue API: `/tracks/search`, `/tracks/lookup`, `/tracks/{id}`, `/artists/{id}`
- [x] Sample catalogue built from real data, with the quality report committed (reports/data-quality.md)

### Milestone 2 deliverables

Acceptance criterion: a user provides a favourite track and receives meaningful similar tracks,
with measurable evaluation results.

- [x] Popularity baseline: global, by genre, by artist, and trending where reliable (ADR-015)
- [x] Content-based model: categorical encoding, numerical normalization, genre TF-IDF, cosine
      similarity, track-to-track and artist similarity
- [x] Similarity retrieval: exact search, pgvector HNSW, and an exact-vs-approximate benchmark
- [x] API: `GET /recommendations/similar/{track_id}`, `/artist/{artist_id}`, `/genre/{genre}`,
      `/popular` (with model versions and evidence-based reasons)
- [x] Offline evaluation: Precision@K, Recall@K, NDCG@K, MAP@K, coverage, diversity@K and novelty,
      on time-aware splits with no future leakage
- [x] Model versioning (`model_versions`, migration `6ec567b027d8`) and the model benchmark report
      (reports/model-benchmark.md)

### Milestone 3 deliverables

Acceptance criterion: TASTIFY learns an individual user's taste (plays, likes, skips, saves,
replays) and generates a personalized mix that reflects it while introducing relevant new artists,
and the hybrid is benchmarked against the Milestone 2 models (reports/hybrid-benchmark.md, ADR-016).

- [x] User data: users, immutable interaction events (idempotent ingestion), declared preferences,
      derived taste profiles (migration `a28199fd7847`); development-only user API until auth (M4)
- [x] Taste profiles: long-term and short-term embeddings, genre and artist affinities, cautious
      negative preferences, exploration preference, declared preferences on top; reproducible,
      updated on every new interaction, stability measured on historical data
- [x] Collaborative filtering: user-user and item-item k-NN, implicit ALS (grid) and BPR on sparse,
      event-weighted, time-decayed matrices; benchmarked against the listening-profile model
- [x] Six independent candidate sources with isolated failures, a deterministic merger that keeps
      source attribution, and an eligibility filter
- [x] Hybrid ranking: calibrated weighted baseline and LightGBM LambdaRank, tuned on chronological
      validation data; served from the model registry without LightGBM in the API
- [x] Diversity and exploration: MMR, artist caps, genre and popularity caps, familiar/balanced/
      explorer modes, category-specific policies (for you, discovery, artist radio)
- [x] Evaluation: test period plus rolling one-day windows; history-size, genre and popularity
      segments; cold start; profile stability; a CC0-only variant for licensing
- [x] Model versioning: `collaborative` and `hybrid` versions with artifacts and lineage; the
      Milestone 2 models kept active and snapshotted as the baseline

## 16. Development Roadmap

### Milestone 0 – Engineering Foundation

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

### Milestone 1 – Data Foundation

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

### Milestone 2 – Recommendation V1

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

### Milestone 3 – Hybrid Recommendation

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

### Milestone 4 – User Application

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

### Milestone 5 – External Integrations

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

### Milestone 6 – Production Release

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

## Milestone 0 progress

- [x] Repository structure (frontend, backend, ml, infrastructure, docs, scripts)
- [x] Next.js + TypeScript + Tailwind CSS frontend
- [x] FastAPI backend with health and readiness endpoints
- [x] PostgreSQL (pgvector) and Redis configuration
- [x] Docker Compose development environment (postgres, redis, migrate, backend, worker, frontend)
- [x] Alembic migrations (async), baseline revision enabling pgvector
- [x] pytest (unit + integration) and Vitest + Playwright frontend testing
- [x] Linting and formatting: ruff, mypy, ESLint, Prettier, pre-commit, EditorConfig
- [x] GitHub Actions CI: quality, tests, migrations, E2E, security, Docker builds
- [x] Engineering documentation, branching strategy, coding standards, ADR-001 to ADR-011
- [ ] Create the GitHub repository and push (manual)
- [ ] Protect `main` (require PR and passing CI), then confirm the first CI run is green (manual)
