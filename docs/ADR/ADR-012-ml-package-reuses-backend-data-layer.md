# ADR-012: The ML package reuses the backend's data layer

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

ADR-008 separates offline pipelines (`ml/`) from the web application. The Milestone 1 pipelines
write the canonical catalogue, whose schema the backend owns through Alembic migrations. The
entity-resolution rules are also needed online later: Milestone 5 imports from Spotify and YouTube
must resolve against the same catalogue.

## Problem

How does `ml/` read and write catalogue tables without duplicating the schema or the resolution
rules?

## Alternatives considered

1. **Separate schema definitions in `ml/`** (SQLAlchemy Core or raw SQL). Independent, but two
   copies of the schema drift apart, and resolution logic gets duplicated.
2. **A shared third package** (for example `packages/catalogue`). The cleanest boundary, but extra
   packaging and tooling overhead for one developer at this stage.
3. **`ml/` imports the backend's data layer** (`app.core`, `app.domains.catalogue` models, writer,
   normalization, resolution, provenance; `app.domains.integrations.clients`).

## Decision

`tastify_ml` imports the backend's data-layer modules directly. It puts `backend/` on `sys.path`
from a checkout, and its `requirements.txt` includes the backend runtime requirements. The rule is
one-directional: `ml/` may import backend data-layer modules, but never `app.api` or request
handling, and the backend never imports `tastify_ml`. Heavy ML dependencies (pandas, scikit-learn,
pyarrow) stay out of the backend image.

## Consequences

- One schema and one resolution policy, tested once and used by both batch and online paths.
- Running `ml/` needs the backend source next to it. That is true in the monorepo and in CI.
- If the boundary starts to blur, extract the catalogue data layer into a shared package (option 2).
