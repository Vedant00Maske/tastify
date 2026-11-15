# ADR-003: PostgreSQL as the primary database

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

The domain model is strongly relational (users, tracks, artists, playlists, interactions,
recommendation logs) with integrity requirements: UUID keys, foreign keys, and unique provider
identifiers (spec §6.4). Some metadata is genuinely variable, and embeddings must be stored and
searched.

## Problem

Which database should be the system of record?

## Alternatives considered

1. **MySQL/MariaDB.** Mature relational database, but weaker JSON support and no first-class vector
   extension comparable to pgvector.
2. **MongoDB.** Flexible documents, but relational integrity (playlists ↔ tracks, ownership checks)
   would move into application code.
3. **Several specialised stores** (relational + document + vector) from day one. More operational
   burden and cross-store consistency problems before any need is measured.

## Decision

Use PostgreSQL (17 locally and in CI) as the single primary database. Model data relationally, use
JSONB only for genuinely variable metadata, and manage the schema exclusively through Alembic
migrations.

## Consequences

- Strong integrity guarantees, rich indexing, transactions across domains, and vector search through
  pgvector (ADR-004).
- One database to back up, restore-test and monitor.
- Connection pooling and query-plan-driven indexing (spec §6.5) must be managed as load grows.
