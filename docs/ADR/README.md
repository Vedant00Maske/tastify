# Architecture Decision Records

Every significant architectural choice is recorded here (spec §18). Each ADR states its context,
problem, alternatives considered, decision, consequences, date and status. To add one, copy
[template.md](template.md) and take the next number. ADRs are never deleted: a reversed decision is
marked _Superseded_ and linked to the ADR that replaces it.

| ADR                                                  | Decision                                           | Status   |
| ---------------------------------------------------- | -------------------------------------------------- | -------- |
| [ADR-001](ADR-001-modular-monolith.md)               | Modular monolith instead of microservices          | Accepted |
| [ADR-002](ADR-002-fastapi-backend.md)                | FastAPI for the backend                            | Accepted |
| [ADR-003](ADR-003-postgresql-primary-database.md)    | PostgreSQL as the primary database                 | Accepted |
| [ADR-004](ADR-004-pgvector-vector-retrieval.md)      | pgvector for initial vector retrieval              | Accepted |
| [ADR-005](ADR-005-independent-recommendation-engine.md) | Independent recommendation engine               | Accepted |
| [ADR-006](ADR-006-provider-abstraction.md)           | Provider abstraction for music integrations        | Accepted |
| [ADR-007](ADR-007-immutable-interaction-events.md)   | Immutable interaction event history                | Accepted |
| [ADR-008](ADR-008-offline-training-online-inference.md) | Separate offline training and online inference  | Accepted |
| [ADR-009](ADR-009-docker-development-deployment.md)  | Docker-based development and deployment            | Accepted |
| [ADR-010](ADR-010-test-driven-core-logic.md)         | Test-driven development for core business logic    | Accepted |
| [ADR-011](ADR-011-development-tooling.md)            | Development tooling and runtime versions           | Accepted |
| [ADR-012](ADR-012-ml-package-reuses-backend-data-layer.md)    | The ML package reuses the backend's data layer     | Accepted |
| [ADR-013](ADR-013-data-sources-and-licensing-posture.md)      | Initial data sources and licensing posture         | Accepted |
| [ADR-014](ADR-014-entity-resolution-policy.md)                | Conservative, explainable entity resolution        | Accepted |
