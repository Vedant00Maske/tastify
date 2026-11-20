# syntax=docker/dockerfile:1

FROM python:3.15-slim AS base
# One numerical thread per process: the service scales by processes (replicas), and numpy's
# BLAS would otherwise start a thread per CPU in every process and oversubscribe the host
# (measured in the Milestone 7 load test: recommendations became about 40x slower).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1
WORKDIR /app

# Local development: dev tooling installed, source bind-mounted by docker-compose, auto-reload.
FROM base AS dev
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "app"]

# Production: runtime dependencies only, non-root user, read-only friendly (no bytecode writes).
# One process per container: scale with replicas (docker-compose.prod.yml), which keeps metrics
# per process and lets the reverse proxy balance and health-check each one.
FROM base AS prod
COPY requirements.txt ./
RUN pip install -r requirements.txt
RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini pyproject.toml ./
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3   CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"]
# Client addresses come from X-Forwarded-For only via TRUSTED_PROXIES (app.api.limits), so
# uvicorn's own proxy-header handling stays off. Access logs come from the app (no secrets).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000",      "--no-access-log", "--no-server-header", "--timeout-graceful-shutdown", "20"]
