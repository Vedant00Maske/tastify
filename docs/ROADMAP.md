# TASTIFY — Development Roadmap

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§16).
> This file is the maintained version: update it in the same pull request as the code it describes.

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
