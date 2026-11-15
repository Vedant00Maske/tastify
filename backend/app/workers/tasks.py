from app.workers.celery_app import celery_app


@celery_app.task(name="system.ping")
def ping() -> str:
    """Round-trip check that the worker and broker are wired correctly."""
    return "pong"
