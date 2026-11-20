"""Aggregates all v1 route modules. Mounted under settings.api_v1_prefix in app.main."""

from fastapi import APIRouter

from app.api.routes import (
    auth,
    catalogue,
    client_errors,
    health,
    integrations,
    interactions,
    playlists,
    recommendations,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(interactions.router)
api_router.include_router(catalogue.router)
api_router.include_router(recommendations.router)
api_router.include_router(playlists.router)
api_router.include_router(integrations.router)
api_router.include_router(client_errors.router)
