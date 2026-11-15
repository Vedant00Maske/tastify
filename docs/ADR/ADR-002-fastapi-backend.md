# ADR-002: FastAPI for the backend

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

The backend serves a JSON API to the Next.js frontend. It validates input, enforces authorization
and coordinates domain services. It must also integrate closely with a Python ML stack (pandas,
scikit-learn, PyTorch) for inference.

## Problem

Which backend framework best balances developer speed, correctness and integration with the ML code?

## Alternatives considered

1. **Django + Django REST Framework.** Batteries included (ORM, admin, auth). Heavier, with
   async support that is less central to its design.
2. **Flask.** Minimal and flexible, but validation, async and OpenAPI generation all need add-ons.
3. **Node.js (NestJS/Express).** A strong ecosystem, but it splits the backend language from the ML
   code and duplicates data-model definitions.
4. **FastAPI.** Async-first, Pydantic validation, automatic OpenAPI, Python.

## Decision

Use FastAPI with Pydantic v2 for request and response schemas, and SQLAlchemy 2.x (async, asyncpg)
for persistence.

## Consequences

- Same language as the ML pipeline, so inference code can be imported directly.
- The generated OpenAPI schema enables API contract tests and typed frontend clients.
- Concerns that Django provides out of the box (auth flows, admin) must be assembled deliberately.
