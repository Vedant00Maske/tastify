# TASTIFY — Local Development

## Prerequisites

| Tool           | Version                               | Notes                                                        |
| -------------- | ------------------------------------- | ------------------------------------------------------------ |
| Docker Desktop | Compose v2.24+                        | Runs PostgreSQL, Redis and, optionally, every app container  |
| Python         | 3.12 (3.11 minimum)                   | Containers and CI use 3.12. The code stays 3.11-compatible.  |
| Node.js        | 24 LTS (22.13 minimum)                | `frontend/.nvmrc`. Containers and CI use 24.                 |
| Git            | recent                                | `.gitattributes` enforces LF line endings                    |

## 1. Configure the environment

```bash
cp .env.example .env            # PowerShell: Copy-Item .env.example .env
```

The defaults work for local development. `.env` is git-ignored; never commit it.

## 2a. Run everything in Docker

```bash
docker compose up --build
```

Startup order: `postgres` and `redis` become healthy, then `migrate` runs `alembic upgrade head`, then
`backend` and `worker` start, then `frontend` starts.

| URL                                       | What                         |
| ----------------------------------------- | ---------------------------- |
| <http://localhost:3000>                   | Frontend                     |
| <http://localhost:8000/api/v1/health>     | Backend liveness             |
| <http://localhost:8000/api/v1/health/ready> | Backend readiness (DB + Redis) |
| <http://localhost:8000/docs>              | Interactive API docs         |

## 2b. Hybrid mode (recommended for day-to-day work on Windows and macOS)

File watching through Docker Desktop bind mounts is slow, so run only the infrastructure in Docker
and the apps on the host:

```bash
docker compose up -d postgres redis
```

**Backend**

```bash
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux/Git Bash: source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload
```

**Worker.** Celery's default pool does not support Windows. Either run the worker in Docker
(`docker compose up -d worker`), or on the host use
`celery -A app.workers.celery_app:celery_app worker --pool=solo --loglevel=INFO`.

**Frontend**

```bash
cd frontend
npm ci
npm run dev
```

The browser only talks to the frontend: `/api/v1/*` is forwarded to the backend by the Next.js
proxy (`src/proxy.ts`), so the session cookie stays first-party. It targets
`http://127.0.0.1:8000` by default; set `API_PROXY_TARGET` to point elsewhere (docker compose sets
`http://backend:8000`). Open the app on an address listed in `CORS_ORIGINS` (by default
`http://localhost:3000` and `http://127.0.0.1:3000`): state-changing requests from any other
origin are rejected. Create an account at `/register`; the app walks you through onboarding.

**ML pipelines** (`ml/`, same virtualenv as the backend)

```bash
pip install -r ml/requirements-dev.txt     # pandas, pyarrow, scikit-learn on top of the backend deps
cd ml
python -m tastify_ml download              # ~8 GB of public dumps into ml/data/raw (git-ignored)
python -m tastify_ml catalogue all         # build the catalogue; see docs/ML_PIPELINE.md
```

`.env` must contain `LISTENS_PSEUDONYM_KEY` (a long random secret) before the `listens` stage runs.
Downloads and processed data live on the drive holding the repository.

### Music service integrations (optional)

`.env` needs `INTEGRATIONS_TOKEN_KEY` (32 random bytes, base64; see `.env.example`) before any
account can be connected. ListenBrainz and MusicBrainz then work without further setup: users
paste their own ListenBrainz token in Settings → Connected services.

- **Spotify:** create an app in the Spotify developer dashboard (the owner needs Premium in
  Development Mode), add the redirect URI `http://127.0.0.1:3000/api/v1/integrations/spotify/callback`,
  add the Spotify accounts that may connect to the app's allow-list (at most five), and set
  `SPOTIFY_CLIENT_ID`.
- **YouTube:** in Google Cloud, enable the YouTube Data API v3, create an OAuth client of type
  "Web application" with the redirect URI
  `http://127.0.0.1:3000/api/v1/integrations/youtube/callback`, add yourself as a test user on the
  consent screen, and set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

Redirect URIs follow `APP_PUBLIC_URL` (default `http://127.0.0.1:3000`), so open the app on that
address. Restart the backend after changing `.env`.

## Everyday commands

| Task                         | Backend (`backend/`)                          | Frontend (`frontend/`)   |
| ---------------------------- | --------------------------------------------- | ------------------------ |
| Lint                         | `ruff check .` (`--fix` to fix)               | `npm run lint`           |
| Format                       | `ruff format .`                               | `npm run format`         |
| Type check                   | `mypy app tests alembic/env.py`               | `npm run typecheck`      |
| Unit tests                   | `pytest -m "not integration"`                 | `npm test`               |
| All tests (needs DB + Redis) | `pytest`                                      | `npm run test:e2e`       |
| Coverage                     | `pytest --cov`                                | `npm run test:coverage`  |

Database and infrastructure:

| Task                                    | Command                                                       |
| --------------------------------------- | ------------------------------------------------------------- |
| Apply migrations                        | `alembic upgrade head` (or `docker compose run --rm migrate`) |
| New migration from model changes        | `alembic revision --autogenerate -m "describe change"`        |
| psql shell                              | `docker compose exec postgres psql -U tastify -d tastify`     |
| redis-cli                               | `docker compose exec redis redis-cli`                         |
| Follow logs                             | `docker compose logs -f backend worker`                       |
| Stop everything                         | `docker compose down`                                         |
| Reset all data (**destroys volumes**)   | `docker compose down -v`                                      |

## Git hooks

After the repository is initialised:

```bash
pre-commit install      # from the backend virtualenv (pre-commit is in requirements-dev.txt)
pre-commit run --all-files
```

## Troubleshooting

- **`tastify_test` database does not exist.** The init script only runs when the PostgreSQL volume
  is first created. Create the database by hand with
  `docker compose exec postgres createdb -U tastify tastify_test`, or reset with
  `docker compose down -v`.
- **Port already in use (5432, 6379, 8000, 3000).** Stop the local service using the port, or change
  the host side of the mapping in `docker-compose.yml`.
- **Vitest fails with `ERR_REQUIRE_ESM`.** Your Node.js is older than 22.12. Upgrade to Node 24 LTS.
- **Hot reload is slow in containers.** Use hybrid mode (2b).
- **Sign-in works but every change fails with `403 Origin not allowed`.** The address in the
  browser is not in `CORS_ORIGINS` (for example `127.0.0.1` when only `localhost` is listed). Add
  it to `.env` and restart the backend.
- **Vitest reports "failed to find the current suite" on Windows.** Run it from PowerShell or
  `cmd` instead of Git Bash (drive-letter casing; see TESTING.md).
