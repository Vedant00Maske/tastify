from app.workers.celery_app import celery_app
from app.workers.tasks import ping


def test_ping_task_returns_pong() -> None:
    # apply() executes the task in-process, so no broker is needed.
    assert ping.apply().get() == "pong"


def test_tasks_are_acknowledged_only_after_completion() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
