# ADR-010: Test-driven development for core business logic

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Recommendation scoring, ranking, diversity, playlist operations and authorization rules are easy to
break subtly, and the damage is hard to see in a UI. The spec treats testing as a first-class
requirement (§11) with explicit quality gates.

## Problem

When and how are tests written, and what do they run against?

## Alternatives considered

1. **Tests after implementation.** Faster at first, but coverage is patchy, and the design is not
   shaped for testability.
2. **Integration tests that mock the database.** Fast, but they miss real SQL, constraint and
   migration behaviour.
3. **Test-first for core logic, with layered tests against real infrastructure where it matters.**

## Decision

- Write tests before the implementation for core business logic: scoring, candidate filtering,
  ranking, diversity, playlist operations, interaction semantics and ownership checks.
- Unit tests are fast and network-free.
- Integration tests run against real PostgreSQL and Redis (an isolated test database), not mocks.
- Playwright covers the critical user journeys.
- CI blocks merges on failing tests, linting, type checks or migrations.

## Consequences

- Slower initial progress, in exchange for regression safety and design pressure toward pure,
  composable functions.
- Integration tests need Docker locally; CI provides service containers.
- ML model quality is validated by offline metrics (Precision@K, NDCG@K, coverage, diversity) as
  well as by tests.
