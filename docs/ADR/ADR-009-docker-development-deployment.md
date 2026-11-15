# ADR-009: Docker-based development and deployment

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

The system needs PostgreSQL with pgvector, Redis, an API, a worker and a frontend. Developers may
use Windows, macOS or Linux. CI and production must run the same software versions.

## Problem

How do we make environments reproducible from a developer laptop through to production?

## Alternatives considered

1. **Native installs of every service.** No container overhead, but version drift between machines,
   and pgvector is awkward to install on Windows.
2. **Dev containers or cloud development environments.** Fully reproducible, but heavier and tied to
   specific tools.
3. **Docker Compose for local infrastructure and apps, with multi-stage Dockerfiles.**

## Decision

Use `docker-compose.yml` for the local stack (postgres, redis, migrate, backend, worker, frontend).
Each app has a multi-stage Dockerfile: a `dev` target with bind mounts and auto-reload, and a `prod`
target that is minimal and runs as a non-root user. CI builds the production images on every change.

## Consequences

- One command brings up a working environment, and CI uses the same database and Redis images.
- File watching through Docker Desktop bind mounts is slow on Windows and macOS. A hybrid mode
  (infrastructure in Docker, apps on the host) is documented in DEVELOPMENT.md.
- Docker Desktop is a prerequisite for contributors.
