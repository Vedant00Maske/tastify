# ADR-001: Modular monolith instead of microservices

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

TASTIFY is an early-stage product built by a small team. It has seven clearly separable domains:
users, catalogue, interactions, recommendations, playlists, integrations and ML. Load is unknown and
expected to be modest at first.

## Problem

How should the system be split into deployable units so that it is simple to build and operate now,
yet can scale and be decomposed later?

## Alternatives considered

1. **Microservices per domain.** Independent scaling and deployments. But network boundaries,
   distributed transactions and data consistency, service discovery and observability overhead would
   all slow iteration before there is any measured need.
2. **Unstructured monolith.** Fastest to start. But domain boundaries erode, which makes later
   extraction and reasoning about the code expensive.
3. **Modular monolith.** One deployable with enforced internal module boundaries.

## Decision

Build a single FastAPI application, plus a Celery worker from the same codebase. Each domain is a
package under `backend/app/domains/` and owns its models, services and schemas. Domains interact
only through service interfaces, never through another domain's ORM models or repositories.

## Consequences

- Single deployment, in-process calls, local transactions and simple local debugging.
- Boundaries are enforced by convention and code review for now. Consider an import-boundary linter
  (for example import-linter) once there are several contributors.
- A domain can be extracted into a service when measured load, failure isolation or team structure
  justifies it. Clean interfaces keep that move mechanical.
