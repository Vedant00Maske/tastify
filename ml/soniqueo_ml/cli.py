"""Command-line entry point: `python -m soniqueo_ml <command>` (run from the ml/ directory)."""

import argparse
import asyncio
import logging
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from app.core.config import get_settings
from soniqueo_ml.config import get_ml_settings
from soniqueo_ml.data import sources
from soniqueo_ml.data.download import RemoteFile, download

logger = logging.getLogger("soniqueo_ml")

DATASETS = ("listens", "canonical", "acousticbrainz", "fma")


def metabrainz_http_client(timeout: float = 120.0) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": get_settings().metabrainz_user_agent},
        timeout=httpx.Timeout(timeout, connect=30.0),
        follow_redirects=True,
    )


def cmd_download(args: argparse.Namespace) -> None:
    settings = get_ml_settings()
    wanted = args.only or list(DATASETS)
    with metabrainz_http_client() as client:
        plan: list[tuple[str, RemoteFile]] = []
        if "listens" in wanted:
            plan += [
                ("listenbrainz", f)
                for f in sources.latest_listen_dumps(client, settings.listens_days)
            ]
        if "canonical" in wanted:
            plan.append(("musicbrainz_canonical", sources.latest_canonical_dump(client)))
        if "acousticbrainz" in wanted:
            plan += [("acousticbrainz", f) for f in sources.acousticbrainz_feature_dumps(client)]
        if "fma" in wanted:
            plan.append(("fma", sources.FMA_METADATA))
        # A few parallel streams: the mirrors throttle each connection, not each client.
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            futures = {
                pool.submit(download, remote, settings.raw_dir / folder, client): remote
                for folder, remote in plan
            }
            for done, future in enumerate(as_completed(futures), start=1):
                future.result()
                logger.info("[%d/%d] %s ready", done, len(plan), futures[future].filename)
    logger.info("All %d files present and verified", len(plan))


async def _run_catalogue(args: argparse.Namespace) -> None:
    from soniqueo_ml.pipelines import catalogue

    stages = catalogue.STAGES if args.stage == "all" else (args.stage,)
    for stage in stages:
        logger.info("=== catalogue stage: %s ===", stage)
        if stage == "listens":
            await catalogue.stage_listens(force=args.force, workers=args.workers)
        elif stage == "mapping":
            await catalogue.stage_mapping()
        elif stage == "genres":
            await catalogue.stage_genres()
        elif stage == "catalogue":
            await catalogue.stage_catalogue(size=args.size, refresh=args.force)
        elif stage == "interactions":
            await catalogue.stage_interactions()
        elif stage == "acousticbrainz":
            await catalogue.stage_acousticbrainz()
        elif stage == "fma":
            await catalogue.stage_fma(limit=args.limit)
        elif stage == "reset":
            await catalogue.stage_reset()
        elif stage == "quality" and not await catalogue.stage_quality():
            raise SystemExit(1)


async def _run_recommend(args: argparse.Namespace) -> None:
    from soniqueo_ml.pipelines import recommendation

    stages = recommendation.STAGES if args.stage == "all" else (args.stage,)
    for stage in stages:
        logger.info("=== recommend stage: %s ===", stage)
        if stage == "evaluate":
            await recommendation.stage_evaluate(fma=not args.skip_fma)
        elif stage == "publish":
            await recommendation.stage_publish()
        elif stage == "benchmark":
            await recommendation.stage_benchmark()
        elif stage == "report":
            await recommendation.stage_report()


async def _run_personalize(args: argparse.Namespace) -> None:
    from soniqueo_ml.pipelines import personalization

    stages = personalization.STAGES if args.stage == "all" else (args.stage,)
    for stage in stages:
        logger.info("=== personalize stage: %s ===", stage)
        if stage == "baseline":
            await personalization.stage_baseline()
        elif stage == "evaluate":
            await personalization.stage_evaluate()
        elif stage == "publish":
            await personalization.stage_publish()
        elif stage == "benchmark":
            await personalization.stage_benchmark()
        elif stage == "report":
            await personalization.stage_report()


async def _run_context(args: argparse.Namespace) -> None:
    from soniqueo_ml.pipelines.context import stage_context

    await stage_context()


async def _run_experiments(args: argparse.Namespace) -> None:
    import json as _json

    from soniqueo_ml.pipelines.experiments import run

    result = await run(
        args.action,
        args.key,
        {"surface": args.surface, "description": args.description, "variant": args.variant},
    )
    print(_json.dumps(result, indent=2, default=str))  # noqa: T201 - command output


def run_async(
    func: Callable[[argparse.Namespace], Coroutine[Any, Any, None]],
) -> Callable[[argparse.Namespace], None]:
    def runner(args: argparse.Namespace) -> None:
        asyncio.run(func(args))

    return runner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="soniqueo_ml", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    p = commands.add_parser("download", help="download and verify the raw source datasets")
    p.add_argument("--only", nargs="+", choices=DATASETS, help="limit to these datasets")
    p.add_argument("--parallel", type=int, default=3, help="concurrent downloads (default 3)")
    p.set_defaults(func=cmd_download)

    from soniqueo_ml.pipelines.catalogue import STAGES

    p = commands.add_parser("catalogue", help="build the music catalogue (Milestone 1 pipeline)")
    p.add_argument(
        "stage",
        choices=("all", *STAGES, "reset"),
        help="stage to run, 'all' in order, or 'reset' to clear derived catalogue tables",
    )
    p.add_argument(
        "--force", action="store_true", help="reprocess/refetch instead of reusing outputs"
    )
    p.add_argument("--workers", type=int, default=4, help="processes for the listens stage")
    p.add_argument("--size", type=int, help="catalogue size (default CATALOGUE_SIZE)")
    p.add_argument("--limit", type=int, help="only the first N FMA tracks (smoke runs)")
    p.set_defaults(func=run_async(_run_catalogue))

    p = commands.add_parser(
        "recommend", help="evaluate, publish and benchmark recommendation models (Milestone 2)"
    )
    p.add_argument(
        "stage",
        choices=("all", "evaluate", "publish", "benchmark", "report"),
        help="stage to run, or 'all' in order",
    )
    p.add_argument("--skip-fma", action="store_true", help="skip the research-only FMA experiment")
    p.set_defaults(func=run_async(_run_recommend))

    from soniqueo_ml.pipelines.personalization import STAGES as PERSONALIZE_STAGES

    p = commands.add_parser(
        "personalize",
        help="hybrid personalization: evaluate, publish and report (Milestone 3)",
    )
    p.add_argument(
        "stage", choices=("all", *PERSONALIZE_STAGES), help="stage to run, or 'all' in order"
    )
    p.set_defaults(func=run_async(_run_personalize))

    p = commands.add_parser(
        "context", help="time-of-day and session context experiment (Milestone 6)"
    )
    p.set_defaults(func=run_async(_run_context))

    p = commands.add_parser(
        "experiments", help="online experiments: create, start, stop, report, prune (Milestone 6)"
    )
    p.add_argument("action", choices=("create", "start", "stop", "report", "prune"))
    p.add_argument("key", nargs="?", help="experiment key, e.g. context-ranking")
    p.add_argument("--surface", default="for_you", help="where it runs (default for_you)")
    p.add_argument("--description", help="what the experiment tests")
    p.add_argument(
        "--variant",
        action="append",
        help="name:weight:param=value,... (first variant is the control), e.g. "
        '"control:0.5:session_weight=0"',
    )
    p.set_defaults(func=run_async(_run_experiments))

    return parser


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    args = build_parser().parse_args(argv)
    args.func(args)
