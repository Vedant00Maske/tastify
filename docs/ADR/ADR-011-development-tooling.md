# ADR-011: Development tooling and runtime versions

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Milestone 0 required concrete choices of runtime versions, package managers and quality tooling
that the specification leaves open. The project owner chose the package managers and styling
approach on 2026-11-16.

## Problem

Which runtimes and tools does the project standardise on?

## Alternatives considered

- **Python dependencies:** uv (fast, lockfile), Poetry (lockfile), or pip with pinned requirements
  files.
- **JavaScript package manager:** pnpm or npm.
- **Styling:** Tailwind CSS or CSS Modules.
- **JS lint/format:** ESLint + Prettier, or Biome.
- **Unit tests:** Vitest or Jest.

## Decision

| Area              | Choice                                                                                       |
| ----------------- | -------------------------------------------------------------------------------------------- |
| Python runtime    | 3.12 in containers and CI. Code stays 3.11-compatible (ruff/mypy target 3.11).               |
| Python deps       | pip, with direct dependencies pinned exactly in `requirements.txt` / `requirements-dev.txt` (owner's choice) |
| Database driver   | asyncpg via SQLAlchemy 2.x async; Alembic with the async environment                         |
| Node.js runtime   | 24 LTS (`frontend/.nvmrc`)                                                                   |
| JS deps           | npm with `package-lock.json` (owner's choice)                                                |
| Frontend          | Next.js 16 App Router, React 19, TypeScript strict, Tailwind CSS v4 (owner's choice)         |
| Python quality    | ruff (lint + format), mypy strict, pre-commit hooks                                          |
| JS quality        | ESLint (Next.js config) + Prettier (with the Tailwind class-sorting plugin)                  |
| Tests             | pytest + pytest-asyncio + httpx; Vitest + Testing Library + jsdom; Playwright                |
| Images            | `pgvector/pgvector:pg17`, `redis:7.4-alpine`, `python:3.12-slim`, `node:24-alpine`           |

## Consequences

- Python transitive dependencies are not locked, so builds can drift between installs. Dependabot
  and CI catch most breakage. If drift causes problems, adopt a lock step (`pip-compile` or
  `uv pip compile`) without changing the requirements-file workflow.
- Version bumps are deliberate pull requests that must pass the full CI suite.
- Contributors need Node.js 22.13 or newer locally. Older versions fail the frontend tests with
  `ERR_REQUIRE_ESM`.
