# TASTIFY — Development Roadmap

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§16).
> This file is the maintained version: update it in the same pull request as the code it describes.

## Current roadmap (revised 2026-11-17)

This plan supersedes the milestone numbering of the original §16 below, which is kept for reference.

| Milestone | Scope | Status |
| --- | --- | --- |
| 0 – Engineering Foundation | Repository, tooling, CI, Docker, migrations, documentation | Done |
| 1 – Music Data Foundation | Data source selection, catalogue ingestion, cleaning, normalization, entity resolution, database design | Done |
| 2 – Recommendation Engine V1 | Popularity baseline, content-based recommendations, similarity search, offline evaluation | Done |
| 3 – Personalized Hybrid Recommendation | Taste profiles, collaborative filtering, embeddings, candidate generation, ranking, diversity | Done |
| 4 – Complete User Application | Authentication, onboarding, discovery dashboard, playlists, feedback, personalized categories | Done (pending review) |
| 5 – Music Platform Integrations | ListenBrainz, MusicBrainz, Spotify and YouTube integrations, subject to API permissions | Done (pending review) |
| 6 – Advanced Recommendation Intelligence | Context-aware ranking, cold-start improvements, natural-language playlists, experimentation, optimization | Done (pending review) |
| 7 – Production Hardening | Security audits, performance, scalability, observability, deployment, data recovery | Done (pending review) |
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
      derived taste profiles (migration `a28199fd7847`); development-only user API, replaced by
      authenticated routes in Milestone 4
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

### Milestone 4 deliverables

Acceptance criterion: a person can create an account, tell TASTIFY their taste, and use a
complete, accessible application (dashboard, discovery, moods, playlists, feedback, taste
analytics, settings) whose recommendations respond to what they like, save and skip (ADR-017).

- [x] Authentication: registration with consent, login, logout, password change, account
      deletion; Argon2id, opaque `HttpOnly` session cookies stored as hashes, Origin-checked
      state-changing requests, rate-limited login and registration (migration `013841aab22d`)
- [x] Authenticated API: `/users/me/…`, `/interactions`, `/recommendations/for-you`; the
      development-only user API removed; data export
- [x] Collections: hidden gems, Surprise Me, "because you listened to", eight mood mixes
      (genre, tempo and danceability recipes; regenerate), artist search and genre browsing
- [x] Playlists: create (empty or generated from a collection), rename, add, remove, reorder,
      regenerate, suggestions, delete; ownership-scoped
- [x] Taste analytics: overview sentence, genre affinity, top artists, weekly trends, emerging and
      fading genres, discovery statistics; only values that can be computed reliably
- [x] Frontend design system: dark-first tokens (colours, type scale, spacing, radii, shadows),
      UI primitives, generated covers and Cover Art Archive artwork, motion with reduced-motion
- [x] App shell: sidebar, header search, persistent player (queue and "listen on" links, no
      simulated playback), mobile navigation, skip link
- [x] Pages: login, register, onboarding (genres, artists, moods and exclusions, exploration
      slider, first mix), home, discover, moods, playlists, taste, search, settings, artist and
      track pages, not-found and error pages; loading, empty, error and offline states
      throughout; WCAG 2.1 AA checked with axe-core; no horizontal scrolling from 360 to 1920 px
- [x] Tests: backend unit and integration tests for auth, privacy, collections and playlists;
      Vitest component and logic tests; Playwright journeys (register, onboarding, login, dashboard,
      feedback, discovery, moods, playlists incl. keyboard reordering, taste, search, settings,
      offline, account deletion, logout) against a mocked API
- [x] Password reset and e-mail verification: delivered in Milestone 7 (needs an e-mail service)

### Milestone 5 deliverables

Acceptance criteria (original §16): provider-specific failures are isolated, tokens are securely
managed, playlist export is retry-safe, provider quotas are respected (ADR-018, INTEGRATIONS.md).

- [x] Provider abstraction: adapters with declared auth kind and capabilities, typed errors,
      offered only when configured
- [x] ListenBrainz: token connection, consented incremental listen import, private playlist export
- [x] MusicBrainz: recording search beyond the catalogue, 1 request per second
- [x] Spotify (Development Mode, verified 2026-11-17): OAuth with PKCE, saved and recently played
      import, playlist export by ISRC; the five-account allow-list explained to users
- [x] YouTube: Google OAuth, private playlist export within the daily quota (Redis meter, 50-track
      cap, cached video ids re-checked after 30 days)
- [x] Retry-safe exports (remote id saved first, found again by marker, items replaced), token
      encryption and refresh, failure isolation (migration `04f15fd99085`)
- [x] Frontend: Connected services in Settings, export menu and status on playlists, MusicBrainz
      fallback in search; backend tests against fake provider servers, E2E journeys
- [ ] Full ListenBrainz history through its export API (background job): later

### Milestone 6 deliverables

Acceptance criterion: changes to recommendation behaviour are justified by offline evidence and
measurable online; users can describe a playlist in their own words and see why each track was
chosen (ADR-019, reports/context-benchmark.md).

- [x] Context measured on unseen days: session (previous hour) +10.5% genre predictability, used
      by default; time of day no better than shuffled dayparts, off by default
- [x] Context-aware for-you: session nudge with explanation; daypart nudge available to experiments;
      browser time zone sent with every request
- [x] Prompt playlists (`POST /recommendations/custom`, FR-016): deterministic interpreter (genres,
      moods, artists, exclusions, tempo, energy, era, popularity, familiarity), evidence-based
      ranking and reasons, interpretation and ignored words returned; saved as regenerable
      playlists; Create page
- [x] Recommendation logging (spec §6.2) and feedback attribution by request id; data export and
      retention
- [x] Online experiments: deterministic weighted assignment, per-variant outcome report with
      confidence intervals and significance test, command-line management
- [x] Cold start: prompt playlists need no history at all, and the session nudge works from a new
      user's first few interactions (declared genres and artists already seed first mixes, M3/M4)
- [x] Optimization: profiled for-you; popularity and genre-profile caches keyed by immutable model
      versions; context scored on the best 250 candidates (773 ms -> about 530 ms in process)

### Milestone 7 deliverables

Acceptance criteria (spec §16 production release): the production environment is available,
critical user journeys pass, no known critical security vulnerabilities, monitoring and error
reporting work, user data deletion works (ADR-020, RUNBOOK.md).

- [x] Security audit and tests (spec §11.6): route sweep, object references, injection, XSS,
      CSRF, forwarded-address spoofing, token leakage; 11 findings fixed, none critical
      ([report](reports/security-audit.md)); security headers and CSP; production refuses
      unsafe settings
- [x] Password reset and e-mail verification: single-use hashed links, no account enumeration,
      SMTP through the worker with retries, pages in the web app, Mailpit locally
- [x] Performance: load test against the production stack; response cache and precomputed
      mixes; batched vector search; indexed track search; cached genre rankings; single-threaded
      BLAS per process: 20 users, about 54 requests/s, every endpoint's p95 below 500 ms
      ([report](reports/load-test.md))
- [x] Scalability: stateless replicas behind Caddy; recommendations on their own service;
      Argon2 off the event loop; pool sizing; statement timeouts; `503` on overload
- [x] Observability: JSON logs with request ids and secret masking; Prometheus metrics for every
      spec §15 application and recommendation metric; 11 alerts; Grafana dashboard; error
      tracking (Sentry-compatible) for the API, worker and web app
- [x] Deployment: production compose stack (HTTPS, read-only non-root containers), CI smoke test
      of that stack on every change, tagged releases to GHCR, approved deploys over SSH,
      rollback
- [x] Data recovery: daily verified backups with an age alert, restore and restore-test
      scripts, token key rotation, daily retention job, catalogue snapshots for new deployments,
      runbook with RPO/RTO
- [x] Privacy documentation: privacy notice and terms pages (operator details to be added
      before launch), linked from registration and settings

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
