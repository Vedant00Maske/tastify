# TASTIFY — Engineering Workflow and Coding Standards

## Branching strategy

The project uses **trunk-based development with short-lived branches**.

- `main` is always releasable. It is protected: changes land only through pull requests, with CI
  passing. Merge by squashing so each PR becomes one commit on `main`.
- Branch from `main` and use a type prefix:

  | Prefix      | Use                                                   | Example                          |
  | ----------- | ----------------------------------------------------- | -------------------------------- |
  | `feat/`     | New functionality                                     | `feat/catalogue-track-search`    |
  | `fix/`      | Bug fixes                                             | `fix/playlist-reorder-off-by-one` |
  | `refactor/` | Behaviour-preserving code changes                     | `refactor/ranking-strategy`      |
  | `test/`     | Tests only                                            | `test/diversity-reranker`        |
  | `docs/`     | Documentation and ADRs                                | `docs/adr-012-auth-sessions`     |
  | `chore/`    | Tooling, dependencies, housekeeping                   | `chore/bump-fastapi`             |
  | `ci/`       | CI/CD changes                                         | `ci/add-staging-deploy`          |

- Keep branches small and short-lived, ideally merged within a few days. Rebase on `main` often.
- Each completed milestone is tagged on `main` with a semantic version (`v0.1.0` for Milestone 0).

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <imperative summary, max ~72 chars>

<optional body: what and why, not how>
```

- **Types:** `feat`, `fix`, `refactor`, `perf`, `test`, `docs`, `build`, `ci`, `chore`.
- **Scopes:** `backend`, `frontend`, `ml`, `infra`, `docs`, `ci`, or a domain (`catalogue`,
  `recommendations`, `playlists`, …).
- Example: `feat(catalogue): add ISRC-based track deduplication`.

## Pull requests

- Fill in the PR template (`.github/pull_request_template.md`) and link the requirement or milestone
  (for example FR-004 or M1).
- CI must be green. Review your own diff before requesting review.
- Schema changes include their Alembic migration. Architectural changes include an ADR.

## Coding standards

### Python (backend, ml)

- ruff handles linting and formatting (100 columns); mypy runs in `strict` mode. Type-annotate every
  function.
- **Layering:** routes (`app/api`) validate input and delegate. Business logic lives in domain
  services (`app/domains/<domain>`). Data access goes through repositories. Routes never contain
  business logic or SQL.
- **Domain boundaries:** a domain calls another domain only through its service interface, never
  through its models or repositories directly (ADR-001).
- Pydantic schemas define every request and response body.
- Async I/O in the API layer. Celery tasks must be idempotent (tasks are acknowledged late and can be
  redelivered).
- UTC everywhere: `datetime.now(UTC)`, `TIMESTAMP WITH TIME ZONE`. UUID primary keys.
- Never log access tokens, credentials or unnecessary personal data.

### TypeScript (frontend)

- ESLint (Next.js core-web-vitals + TypeScript rules) and Prettier. TypeScript `strict`; avoid `any`.
- Use Server Components by default; add `"use client"` only where interactivity requires it.
- Feature code lives in `src/features/<feature>`. Shared UI goes in `src/components`. All backend
  calls go through `src/services/api-client.ts`.
- Components must be accessible: semantic elements, labels, keyboard navigation and visible focus.

### Testing

- Write tests first for core business logic: scoring, ranking, diversity, playlist operations and
  interaction semantics (ADR-010).
- Name tests after the behaviour they verify.
- See [TESTING.md](TESTING.md) for layout and commands.

## Definition of Done

A feature is not complete merely because it works on a developer's machine. Every feature has:

- Defined requirements and documented interfaces.
- Implementation with input validation and error handling.
- Unit tests, plus integration tests where applicable.
- Logging and monitoring where relevant.
- A security review (authorization and ownership checks, secrets, injection).
- Updated documentation.
- Code review and successful CI checks.

ML features also need:

- Dataset provenance and feature definitions.
- Reproducible experiments, evaluation results against a baseline, a model version and known
  limitations.

## Architecture Decision Records

Write an ADR in [ADR/](ADR/) for any decision that is costly to reverse or that shapes how others
write code: a new datastore, framework, cross-cutting pattern, external provider or deployment
change. Copy [ADR/template.md](ADR/template.md) and take the next number.
