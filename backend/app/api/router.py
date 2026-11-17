"""Aggregates all v1 route modules. Mounted under settings.api_v1_prefix in app.main."""

from fastapi import APIRouter

from app.api.routes import catalogue, health, recommendations, users

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(catalogue.router)
api_router.include_router(recommendations.router)
api_router.include_router(users.router)
