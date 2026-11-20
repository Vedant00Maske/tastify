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

## Implemented deployment (Milestone 7)

Design and measurements: [ADR-020](ADR/ADR-020-production-hardening.md),
[load test](reports/load-test.md), [security audit](reports/security-audit.md). Day-to-day
operations (deploy, roll back, restore, rotate secrets, alerts): [RUNBOOK.md](RUNBOOK.md).

### Environments

| Environment | Where | Settings |
| --- | --- | --- |
| Local development | `docker-compose.yml`, or apps on the host (DEVELOPMENT.md) | `.env` |
| Automated testing | pytest, Vitest, Playwright (mocked API) | `tests/conftest.py`, `playwright.config.ts` |
| Staging (smoke) | `docker-compose.prod.yml` + `infrastructure/deployment/docker-compose.smoke.yml`, in CI on every change and locally | `infrastructure/deployment/smoke.env` (plain HTTP, Mailpit) |
| Production | `docker-compose.prod.yml` on a server | `.env.production` (from `.env.production.example`) |

### Production stack (`docker-compose.prod.yml`)

```
Internet ──443──> caddy ──/api/v1/recommendations/*──> recommender × RECOMMENDER_REPLICAS
                    │────/api/v1/*─────────────────────> api × API_REPLICAS
                    └────everything else───────────────> frontend (Next.js)
api, recommender, worker, beat ──> postgres (pgvector, pg_stat_statements), redis
backup ──> postgres (daily pg_dump to the backups volume)
prometheus ──> api, recommender, worker (/metrics)    grafana, alertmanager (profile "monitoring")
```

| Service | Image | Role |
| --- | --- | --- |
| `caddy` | `caddy:2.11` | HTTPS (automatic certificates), HSTS, routing by path, compression, 2 MB body limit, JSON access log without query strings or cookies. The only service with published ports. |
| `frontend` | `frontend/Dockerfile` `prod` | Next.js standalone server: pages, CSP and security headers, image optimizer. |
| `api` | `backend/Dockerfile` `prod` | FastAPI, one process per replica: accounts, catalogue, feedback, playlists, integrations. |
| `recommender` | same image | The same API, serving `/api/v1/recommendations/*` only, so CPU-heavy ranking cannot slow anything else. |
| `worker` | same image | Celery (threads): e-mail delivery with retries, precomputed mixes, metrics on port 9100. |
| `beat` | same image | Celery scheduler: the daily retention job. Exactly one. |
| `migrate` | same image | `alembic upgrade head` before the apps start. Builds the backend image. |
| `postgres` | `pgvector/pgvector:pg17` | Tuned via `POSTGRES_*` settings; slow statements (over 1 s) logged. |
| `redis` | `redis:7.4-alpine` | Password, append-only persistence, `volatile-lru` eviction (only expiring keys: never the job queue). |
| `backup` | `pgvector/pgvector:pg17` | `infrastructure/backup/backup.sh`: daily dumps, retention, health check on backup age. |
| `prometheus`, `alertmanager`, `grafana` | pinned images, profile `monitoring` | Metrics, 11 alert rules, the "TASTIFY overview" dashboard; on `127.0.0.1` only. |

Containers run as non-root users with read-only root filesystems and `no-new-privileges`; logs
rotate (5 × 20 MB per container). Images pin numerical libraries to one thread per process
(`OMP_NUM_THREADS=1`): scale by replicas, not threads.

### First deployment

Requirements: a Linux server with Docker Engine and the Compose plugin, a domain whose DNS points
to it, ports 80 and 443 open, an SMTP account for e-mail. Sizing: 4 vCPUs and 8 GB run
2 api + 2 recommender replicas comfortably; add recommender replicas up to the core count.

1. Clone the repository on the server and check out the release tag.
2. `cp .env.production.example .env.production`, fill in every `change-me`
   (`openssl rand -base64 32` for passwords and the token key), `chmod 600 .env.production`.
   Keep a copy of it in a password manager.
3. Check it: `docker compose -f docker-compose.prod.yml --env-file .env.production run --rm api python -m app.cli check-config`
4. Start: `sh scripts/deploy.sh <tag>` (pulls published images; or
   `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --wait`
   to build on the server).
5. Load the catalogue (next section), then start the monitoring profile:
   `docker compose -f docker-compose.prod.yml --env-file .env.production --profile monitoring up -d`
   and open Grafana through a tunnel: `ssh -L 3001:127.0.0.1:3001 <server>`.
6. Run the smoke test against the public address:
   `python3 scripts/smoke_test.py --base https://<domain>` (needs `httpx`).
7. Fill in the operator's details in the privacy notice and terms
   (`frontend/src/app/(legal)/`) and have them reviewed before inviting people.

### Loading the catalogue

The catalogue and models are built by the ML pipelines (ML_PIPELINE.md) on a machine with the
datasets. A snapshot moves them to a new deployment; user data is never included:

```bash
# On the build machine (development database):
docker exec -i tastify-postgres-1 sh -s export - < infrastructure/backup/catalogue.sh > catalogue.dump
# On the server (a deployment without users; the import refuses otherwise):
docker compose -f docker-compose.prod.yml --env-file .env.production cp catalogue.dump backup:/backups/catalogue.dump
docker compose -f docker-compose.prod.yml --env-file .env.production exec backup sh /scripts/catalogue.sh import /backups/catalogue.dump
docker compose -f docker-compose.prod.yml --env-file .env.production restart api recommender worker
```

Both databases must be at the same schema revision. Once users exist, the catalogue is updated
by running the pipelines against the production database, which publish new model versions.

### Deployment process status (spec §14)

| Step | Where |
| --- | --- |
| 1-7. Branch, pull request, formatting and linting, unit, integration and security checks, Docker build | `.github/workflows/ci.yml` |
| 8. Staging deployment | `deploy-smoke` job: the production stack from the commit |
| 9. Smoke tests | `scripts/smoke_test.py`, backup and restore test, unsafe production settings refused |
| 10. Production deployment approved | `.github/workflows/release.yml`: a version tag publishes images to GHCR; the `production` environment's reviewers approve; `scripts/deploy.sh` runs over SSH |

### Database management

- Version-controlled migrations, applied by `migrate` before every start; CI applies, rolls back
  and re-applies them on a clean database and checks models and migrations agree.
- Automated backups and a restore test: RUNBOOK.md.
- Connection pooling per process: `DB_POOL_SIZE` + `DB_MAX_OVERFLOW` (keep replicas × that sum
  below `POSTGRES_MAX_CONNECTIONS`); every statement is capped by `DB_STATEMENT_TIMEOUT_MS`
  (15 s; the ML pipelines run without the cap).
- Query statistics: `pg_stat_statements` (RUNBOOK.md, `SlowDatabase`).

### Monitoring (spec §15)

**Logs.** JSON lines (`LOG_FORMAT=json`) with `request_id` (also returned as `X-Request-ID`, and
set by Caddy so its log and the API's share it). Access lines carry method, route template,
status and duration. Secrets are masked before writing.

**Metrics** (Prometheus names; `/metrics` on each API process, port 9100 on the worker):

| Spec metric | Metric |
| --- | --- |
| Request count, error rate | `tastify_http_requests_total{method,route,status}` |
| API latency | `tastify_http_request_duration_seconds` |
| Database query latency | `tastify_db_query_duration_seconds{operation}` |
| Cache hit rate | `tastify_cache_requests_total{cache,result}` (response cache, genre members, popularity rankings, model artifacts, genre profiles) |
| Background job failures | `tastify_background_jobs_total{task,outcome}`, `tastify_emails_total` |
| External provider failures | `tastify_provider_requests_total{provider,outcome}` |
| Candidate generation time, ranking latency | `tastify_recommendation_stage_seconds{surface,stage}` |
| Number of candidates retrieved | `tastify_recommendation_candidates{surface}` |
| Model version distribution | `tastify_recommendations_served_total{surface,model_version}` |
| Feedback conversion inputs | `tastify_feedback_events_total{event_type,attributed}` with served items; per-experiment conversion: `python -m tastify_ml experiments report` |
| Also | requests in flight, rate-limit refusals, overload, web app errors, backup age |

Recommendation coverage, diversity and the user-experience metrics (save rate, acceptance, skip
rate, retention) are computed from the recommendation logs and events, in aggregate, by the
evaluation pipelines and the experiment report; product analytics follow in Milestone 8.

**Error tracking.** `SENTRY_DSN` (Sentry or a compatible service) for the API and the worker,
without request bodies, cookies, headers or user ids. Browser errors are reported to
`POST /api/v1/client-errors` and forwarded from there.

**Alerts** (`infrastructure/monitoring/prometheus/alerts.yml`): instance down, server errors
above 2%, database pool exhausted, recommendation and API latency, slow database, failing jobs,
undelivered e-mail, backup older than 26 hours, provider errors, web app errors. Routing:
`infrastructure/monitoring/alertmanager/alertmanager.yml` (add an e-mail receiver). Responses:
RUNBOOK.md.

### Local development stack

`docker-compose.yml` runs PostgreSQL, Redis, migrations, the API with auto-reload, the worker
(threads), beat, Mailpit (e-mail inbox at http://127.0.0.1:8025) and the Next.js dev server.
DEVELOPMENT.md has the details.
