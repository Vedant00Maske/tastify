# ADR-020: Production hardening: edge, scaling, observability, recovery and account recovery

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Milestone 7 turns the application into something that can run for real users: security audit
and testing (spec §11.6, §12), performance against the targets in §4 (recommendation p95 below
500 ms for cached and precomputed responses; 99.5% availability), horizontal scaling,
observability (§15: structured logs, metrics, error tracking), deployment (§14: staging, smoke
tests, approved production releases) and data recovery (automated backups, restore testing).
Password reset and e-mail verification were deferred here from Milestone 4 because they need
outgoing e-mail.

The starting point: a single API process, no metrics or error tracking, development compose
only, no backups, unstructured logs that included uvicorn's access lines (full URLs, including
OAuth callback codes), and rate limits only on sign-in and registration.

## Problem

How is SONIQUEO deployed, scaled, observed and recovered with the fewest moving parts that still
meet the spec's targets, without weakening its privacy guarantees (no third-party scripts in the
browser, no personal data in logs or error reports)?

## Alternatives considered

1. **A managed platform (Kubernetes, a PaaS).** Rolling updates and autoscaling built in, but a
   large operational and cost step for a beta, and the choice of provider is not made yet.
2. **One container per service, scaled by process count inside it (uvicorn workers).** Simple,
   but per-process metrics need Prometheus multiprocess mode, the proxy cannot health-check
   processes individually, and CPU-heavy ranking shares event loops with every other request.
3. **Docker Compose on one host behind Caddy: one process per container, scaled by replicas,
   with recommendations and the general API as separate services of the same image; Redis
   caches; Prometheus, Grafana and Alertmanager on the same network; scripted backups; a CI
   smoke test of the production stack; images published by tag and deployed after approval.**

## Decision

Option 3. Each element was measured or tested before being kept; numbers are in
[load-test.md](../reports/load-test.md) and [security-audit.md](../reports/security-audit.md).

**Edge and routing.** Caddy terminates HTTPS (automatic certificates, HSTS) and routes, all on
one origin: `/api/v1/recommendations/*` to the `recommender` service, other `/api/v1/*` to `api`,
everything else to Next.js. Replicas are discovered through Docker DNS and balanced by least
connections. `/metrics` is never routed. Caddy replaces client-supplied `X-Forwarded-For` unless
the peer is a configured trusted proxy, and its access log drops query strings and cookies.

**Scaling.** One process per container. The load test showed that numpy's BLAS starts a thread
per CPU in every process: with 8 replicas on 16 CPUs this oversubscribed the host and made
ranking about 40 times slower. Images pin `OMP_NUM_THREADS=1` and `OPENBLAS_NUM_THREADS=1`.
Splitting recommendations from the general API kept sign-in, catalogue and playlist requests
fast while ranking was saturated. Argon2 hashing (64 MiB, tens of milliseconds) moved off the
event loop into a bounded thread pool (four at a time).

**Performance.**
- *Cached and precomputed responses* (spec §4): for-you, hidden gems and because-you-listened
  are cached in Redis under a fingerprint of everything they depend on (latest events and their
  count, declared preferences, active model versions) plus the request. Any feedback or
  preference change produces a new key, so a stale mix is never served; ten minutes bound the
  time-dependent session context. Every serve gets a fresh `request_id`, so logging and
  feedback attribution are unchanged. After feedback, the worker precomputes the default mixes
  for the new state (`recommendations.precompute`), so the next home page is a cache hit.
- *Database:* content candidates fetch every seed's neighbours in one `LATERAL` HNSW query
  instead of one round trip per seed (identical results, 3.7 times faster); track search finds
  candidates through the trigram indexes before scoring (identical top 20 on 30 test queries,
  5 times faster); genre and tag rankings, identical for every user, are cached per process by
  popularity version; vectors convert with `tolist`. Statements are capped at 15 s
  (`statement_timeout`); pool exhaustion answers `503` with `Retry-After`, not `500`.
- Result with 20 simulated listeners: about 54 requests/s, every endpoint's p95 below 500 ms
  (cached for-you 124 ms, computed 475 ms), against 10 requests/s and 11 s before.

**Security.** A route sweep test requires every API operation to be explicitly public or to
answer `401`; tests cover insecure direct object references, SQL injection, stored script
payloads, CSRF, forwarded-address spoofing, token leakage into logs and rate-limit bypass.
Findings fixed: an open redirect after sign-in (`/\evil.example`), unbounded password
confirmations (password change and account deletion could be used to guess a stolen session's
password), a rate-limit counter that could be left without expiry, OAuth codes in uvicorn's
access log, unbounded request bodies, interactive API docs in production. Security headers on
every response; a content security policy on pages that allows only same-origin resources.
Inline scripts stay allowed: the App Router streams its payload in inline scripts, and nonces
would force per-request rendering of every page (incompatible with the prerendering
`cacheComponents` relies on). The other directives still block foreign scripts, connections,
framing, plugins and form targets, and React escapes all user text. In production the API
refuses to start with unsafe settings (non-HTTPS origins, insecure cookies, development
database password, no SMTP).

**Account recovery.** Single-use tokens (SHA-256 stored, like sessions) in `account_tokens`:
password reset (60 minutes) and address verification (48 hours). Issuing a new link invalidates
older ones; a token counts only for the address it was sent to; a reset signs out every session
and proves the address. Reset requests answer identically for unknown addresses, and the work
happens after the response so timing reveals nothing. E-mail is queued and delivered by the
worker over SMTP with exponential backoff. Without SMTP the features answer `503`, honestly.

**Observability.** JSON logs with a request id (from Caddy, or generated) on every line and
response; secrets are masked by pattern before anything is written; access lines carry route
templates, never paths with ids or query strings. Prometheus metrics: requests, latency, errors,
in-flight, database statement latency, cache hit rates, rate-limit refusals, overload,
background jobs, e-mails, provider calls, ranking stage times, candidate counts, served model
versions, feedback events, web app errors and backup age. Eleven alert rules; a provisioned
Grafana dashboard. Errors go to Sentry or a compatible service when `SENTRY_DSN` is set, with
request bodies, cookies, headers and user ids removed. The web app reports rendering and
uncaught errors to the API (`POST /client-errors`) instead of loading a third-party script.

**Deployment.** `docker-compose.prod.yml` (Caddy, frontend, api and recommender replicas,
worker, beat, migrate, PostgreSQL with `pg_stat_statements`, Redis with a password and
`volatile-lru`, backups; read-only filesystems, no new privileges, log rotation; monitoring as
a profile). CI starts that stack from each commit with a smoke overlay and runs
`scripts/smoke_test.py` (pages and headers, health, registration, e-mail verification and
password reset through the real worker and SMTP, playlists, recommendations, export, CSRF,
deletion), a backup and restore test, and checks that unsafe production settings are refused.
Version tags publish images to the GitHub Container Registry; deployment runs
`scripts/deploy.sh` over SSH after approval in the `production` environment (backup first,
migrate, recreate, check readiness, record the version for rollback).

**Recovery.** Daily `pg_dump` backups (custom format, verified listable, atomic, kept 14 days),
their age exposed as a metric with an alert after 26 hours, a restore script and a monthly
restore test (`verify.sh`). Provider-token key rotation without downtime
(`INTEGRATIONS_TOKEN_PREVIOUS_KEYS`, `python -m app.cli rotate-token-key`). A daily retention
job deletes expired sessions and e-mail links, recommendation logs past retention and stale
provider ids. Catalogue snapshots move the catalogue and models (never user data) to a new
deployment.

## Consequences

- One host is a single point of failure: availability depends on that host (99.5% allows about
  3.6 hours of downtime a month). Recovery is a restore from the newest backup (RPO 24 hours,
  RTO about an hour, RUNBOOK.md). Moving to managed PostgreSQL or a second host is a deployment
  change, not an application change: the services are stateless and configured by environment.
- Compose recreates replicas together, so a deploy has a few seconds of unavailability.
- `'unsafe-inline'` scripts remain allowed by the CSP (see above); revisit if pages stop being
  prerendered or Next.js supports hashes for streamed payloads.
- Per-process caches are bounded and keyed by immutable versions; the Redis response cache is
  bounded by its ten-minute lifetime and Redis's memory limit.
- Spotify and YouTube still need real credentials to be verified end to end (Milestone 5).
- The privacy notice and terms describe the actual behaviour but must be completed with the
  operator's identity and reviewed for the jurisdiction before a public launch.
