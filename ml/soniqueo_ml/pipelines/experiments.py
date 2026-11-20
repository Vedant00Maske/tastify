"""Online experiments from the command line (Milestone 6; ADR-019).

    python -m soniqueo_ml experiments create context-ranking --surface for_you \
        --variant control:0.5:session_weight=0 --variant session:0.5:session_weight=0.1 \
        --description "Does the session nudge improve feedback on For you?"
    python -m soniqueo_ml experiments start context-ranking
    python -m soniqueo_ml experiments report context-ranking
    python -m soniqueo_ml experiments stop context-ranking
    python -m soniqueo_ml experiments prune        # delete logs past their retention
"""

import json
import logging
from typing import Any

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.domains.recommendations import logging_service

logger = logging.getLogger(__name__)


def parse_variant(text: str) -> dict[str, Any]:
    """ "name:weight:key=value,key=value" -> {"name", "weight", "params"} (values as JSON)."""
    name, _, rest = text.partition(":")
    weight, _, params_text = rest.partition(":")
    params: dict[str, Any] = {}
    for pair in filter(None, params_text.split(",")):
        key, _, value = pair.partition("=")
        try:
            params[key.strip()] = json.loads(value)
        except json.JSONDecodeError:
            params[key.strip()] = value
    return {"name": name.strip(), "weight": float(weight or 1.0), "params": params}


async def run(action: str, key: str | None, options: dict[str, Any]) -> dict[str, Any]:
    async with SessionFactory() as session:
        if action == "prune":
            days = get_settings().recommendation_log_retention_days
            deleted = await logging_service.prune(session, days)
            return {"deleted_requests": deleted, "retention_days": days}
        if key is None:
            raise SystemExit("an experiment key is required")
        if action == "create":
            variants = [parse_variant(v) for v in options.get("variant") or []]
            experiment = await logging_service.save_experiment(
                session, key, options.get("description") or key, options["surface"], variants
            )
            return {"experiment": experiment.key, "status": experiment.status, "variants": variants}
        if action in ("start", "stop"):
            experiment = await logging_service.set_status(
                session, key, "running" if action == "start" else "stopped"
            )
            return {"experiment": experiment.key, "status": experiment.status}
        if action == "report":
            return await logging_service.report(session, key)
    raise SystemExit(f"unknown action {action}")
