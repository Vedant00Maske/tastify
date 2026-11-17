# TASTIFY — Deployment and Observability

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§14–15).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 14. Deployment Architecture

### Environments

1. Local development.
2. Automated testing.
3. Staging.
4. Production.

### Deployment Process

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

### Containerization

Initial containers:

- frontend
- backend
- postgres
- redis
- worker

ML training can run as a separate job rather than requiring a continuously running training service.

### Database Management

- Version-controlled migrations.
- Automated backups.
- Restore testing.
- Connection pooling.
- Migration validation.

---

## 15. Monitoring and Observability

### Application Metrics

- Request count.
- Error rate.
- API latency.
- Database query latency.
- Cache hit rate.
- Background job failures.
- External provider failures.

### Recommendation Metrics

- Candidate generation time.
- Ranking latency.
- Number of candidates retrieved.
- Recommendation coverage.
- Recommendation diversity.
- Feedback conversion.
- Model version distribution.

### User Experience Metrics

- Playlist save rate.
- Recommendation acceptance.
- Track skip rate.
- Repeat listening.
- User retention.
- User satisfaction.

Monitor these in aggregate and respect user consent and privacy.

---

## Current state (Milestone 0)

**Local development** uses `docker-compose.yml`:

| Service    | Image / build                 | Purpose                                                |
| ---------- | ----------------------------- | ------------------------------------------------------ |
| `postgres` | `pgvector/pgvector:pg17`      | Primary database with pgvector                         |
| `redis`    | `redis:7.4-alpine`            | Cache and Celery broker / result backend               |
| `migrate`  | `backend/Dockerfile` (`dev`)  | One-shot `alembic upgrade head` before the apps start  |
| `backend`  | `backend/Dockerfile` (`dev`)  | FastAPI with auto-reload on port 8000                  |
| `worker`   | `backend/Dockerfile` (`dev`)  | Celery worker                                          |
| `frontend` | `frontend/Dockerfile` (`dev`) | Next.js dev server on port 3000                        |

**Production images** are the `prod` targets of both Dockerfiles. The backend image contains runtime
dependencies only and runs as a non-root user. The frontend image is the Next.js standalone server
running as a non-root user. Both are built in CI on every change but not pushed anywhere yet.

**Probes** for orchestrators and load balancers:

- Liveness: `GET /api/v1/health`
- Readiness: `GET /api/v1/health/ready` (returns `503` until PostgreSQL and Redis are reachable)

**Deployment process status** (steps from the list above):

- Steps 1–7 (branch, PR, lint/format, unit tests, integration tests, security checks, Docker build)
  are automated in GitHub Actions.
- Steps 8–10 (staging, smoke tests, production approval) are planned for Milestone 6.
- The frontend serves the API on its own origin: set `API_PROXY_TARGET` (runtime) to the
  backend's internal URL. `NEXT_PUBLIC_API_URL` (build time) defaults to `/api/v1` and normally
  stays unset.
- Backend settings per environment: `CORS_ORIGINS` (the public frontend origin; also the CSRF
  allow-list), `TRUSTED_PROXIES` (the frontend's address or network, so rate limits see real
  client addresses) and HTTPS in front of both (session cookies are `Secure` outside local and
  test).
