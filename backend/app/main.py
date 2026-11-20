"""FastAPI application entry point (`uvicorn app.main:app`)."""

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.observability import init_error_tracking
from app.core.redis import redis_client
from app.domains.auth.dependencies import OriginCheckMiddleware

logger = logging.getLogger(__name__)


class UnsafeConfigurationError(RuntimeError):
    pass


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await redis_client.aclose()
    await engine.dispose()


def _check_deployment_settings() -> None:
    settings = get_settings()
    if not settings.is_deployed:
        return
    problems = settings.deployment_problems()
    for problem in problems:
        logger.warning("unsafe setting: %s", problem)
    if problems and settings.environment == "production":
        raise UnsafeConfigurationError(
            "refusing to start in production with unsafe settings: " + "; ".join(problems)
        )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    _check_deployment_settings()
    init_error_tracking("api")

    docs = settings.api_docs_enabled
    prefix = settings.api_v1_prefix
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        openapi_url=f"{prefix}/openapi.json" if docs else None,
        docs_url=f"{prefix}/docs" if docs else None,
        redoc_url=f"{prefix}/redoc" if docs else None,
        lifespan=lifespan,
    )
    # Starlette runs the last-added middleware first: the request context wraps everything (ids,
    # body limit, security headers, access log, metrics); CORS answers preflights; the Origin
    # check guards state-changing requests (CSRF, ADR-017).
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router, prefix=prefix)

    if settings.metrics_enabled:

        @app.get("/metrics", include_in_schema=False)
        async def metrics(request: Request) -> Response:
            """Prometheus scrape endpoint; outside /api/v1, so never reachable through the
            public proxy. With METRICS_TOKEN, a bearer token is required as well."""
            token = settings.metrics_token
            if token:
                sent = request.headers.get("authorization", "")
                if not hmac.compare_digest(sent.encode(), f"Bearer {token}".encode()):
                    return Response(status_code=status.HTTP_401_UNAUTHORIZED)
            return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
