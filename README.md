# TASTIFY

Personalized music discovery and playlist generation. TASTIFY learns individual musical taste from
listening history, interactions, moods, genres and discovery preferences, and owns its recommendation
intelligence. Music platforms serve only as metadata, user-data and playlist-export providers.

**Status:** Milestone 0 (engineering foundation) complete. See [docs/ROADMAP.md](docs/ROADMAP.md).
The approved product and engineering specification is [TASTIFY_v0.1.md](TASTIFY_v0.1.md).

## Tech stack

| Layer           | Technology                                                            |
| --------------- | --------------------------------------------------------------------- |
| Frontend        | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4        |
| Backend         | FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic                   |
| Data            | PostgreSQL 17 + pgvector, Redis 7                                     |
| Background jobs | Celery (Redis broker)                                                 |
| ML (planned)    | pandas, NumPy, scikit-learn, PyTorch, MLflow                          |
| Quality         | ruff, mypy, pytest · ESLint, Prettier, Vitest, Playwright · pre-commit |
| Delivery        | Docker, Docker Compose, GitHub Actions                                |

## Quick start

Prerequisites: Docker Desktop, Python 3.12, Node.js 24 LTS.

```bash
cp .env.example .env              # PowerShell: Copy-Item .env.example .env
docker compose up --build
```

- Frontend: <http://localhost:3000>
- API health: <http://localhost:8000/api/v1/health> (readiness: `/api/v1/health/ready`)
- API docs: <http://localhost:8000/docs>

For hybrid mode (apps on the host, faster reloads), tests and everyday commands, see
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Repository layout

```text
tastify/
├── frontend/              Next.js app: src/{app,components,features,hooks,services,types}, e2e/
├── backend/               FastAPI app, Celery worker, Alembic migrations, tests
│   ├── app/
│   │   ├── api/           routing and request validation (/api/v1)
│   │   ├── core/          settings, logging, database and Redis clients
│   │   ├── domains/       users, catalogue, interactions, recommendations, playlists, integrations
│   │   ├── repositories/  data-access layer
│   │   ├── schemas/       shared Pydantic schemas
│   │   └── workers/       Celery app and tasks
│   ├── alembic/           database migrations
│   └── tests/             unit/ and integration/
├── ml/                    offline data, feature, training and evaluation pipelines
├── infrastructure/        docker/ (service config), deployment/, monitoring/
├── docs/                  engineering documentation and ADRs
├── scripts/               developer and operations scripts
├── .github/               CI workflow, Dependabot, PR template
└── docker-compose.yml
```

## Documentation

| Document                                           | Contents                                                 |
| -------------------------------------------------- | -------------------------------------------------------- |
| [PRD](docs/PRD.md)                                 | Product vision, features, functional and non-functional requirements |
| [HLD](docs/HLD.md)                                 | Architecture, components, data flow, infrastructure      |
| [LLD](docs/LLD.md)                                 | Design principles, application classes, data structures  |
| [DATABASE](docs/DATABASE.md)                       | Entities, relationships, rules, indexes, migration workflow |
| [API_SPEC](docs/API_SPEC.md)                       | REST endpoints and implementation status                 |
| [ML_PIPELINE](docs/ML_PIPELINE.md)                 | Data pipeline and recommendation engine design           |
| [INTEGRATIONS](docs/INTEGRATIONS.md)               | Provider abstraction and provider constraints            |
| [TESTING](docs/TESTING.md)                         | Testing strategy and how to run tests                    |
| [SECURITY](docs/SECURITY.md)                       | Security and privacy architecture                        |
| [DEPLOYMENT](docs/DEPLOYMENT.md)                   | Environments, containers, observability                  |
| [ROADMAP](docs/ROADMAP.md)                         | Milestones and progress                                  |
| [DEVELOPMENT](docs/DEVELOPMENT.md)                 | Local setup and everyday commands                        |
| [CONTRIBUTING](docs/CONTRIBUTING.md)               | Branching, commits, coding standards, Definition of Done |
| [ADR](docs/ADR/README.md)                          | Architecture Decision Records                            |
