"""Milestone 1 catalogue pipeline (docs/ML_PIPELINE.md, "Implemented pipeline").

    listens -> mapping -> genres -> catalogue -> interactions -> acousticbrainz -> fma -> quality

Every stage is idempotent and recorded as an ingestion job (parameters, statistics, sampled errors).
Raw inputs stay untouched in ml/data/raw; derived datasets go to ml/data/processed.
"""

import asyncio
import logging
import os
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.domains.catalogue.models import RawRecord, TrackExternalId, TrackFeatures
from app.domains.catalogue.provenance import (
    JobRecorder,
    ensure_data_source,
    source_id_for,
    store_raw_record,
)
from app.domains.catalogue.writer import CatalogueWriter, outcome_counts
from app.domains.integrations.clients.metabrainz import ListenBrainzClient, MusicBrainzClient
from tastify_ml.config import MlSettings, get_ml_settings
from tastify_ml.data import sources
from tastify_ml.data.ingestion import acousticbrainz, fma, listenbrainz_listens
from tastify_ml.data.ingestion.listenbrainz_metadata import parse_recording
from tastify_ml.data.ingestion.musicbrainz_canonical import (
    build_key_mapping,
    iter_canonical_batches,
)
from tastify_ml.data.normalization.listen_mapping import (
    listen_files,
    map_listens,
    mapped_listens,
    recording_popularity,
    unique_listen_keys,
)
from tastify_ml.data.quality.checks import run_checks
from tastify_ml.data.quality.report import collect_summary, write_report

logger = logging.getLogger(__name__)

COMMIT_EVERY = 500


class Paths:
    def __init__(self, settings: MlSettings) -> None:
        self.raw = settings.raw_dir
        self.processed = settings.processed_dir
        self.listens = self.processed / "listens"
        self.mapped = self.processed / "listens_mapped"
        self.key_mapping = self.processed / "listen_key_mapping.parquet"
        self.popularity = self.processed / "recording_popularity.parquet"
        self.interactions = self.processed / "interactions.parquet"
        self.reports_history = settings.data_dir / "reports"


async def register_sources(session: AsyncSession) -> None:
    for info in sources.ALL_SOURCES:
        await ensure_data_source(
            session,
            key=info.key,
            name=info.name,
            homepage_url=info.homepage_url,
            license=info.license,
            license_url=info.license_url,
            usage_restriction=info.usage_restriction.value,
            attribution=info.attribution,
            notes=info.notes,
        )
    await session.commit()


async def _start(session: AsyncSession, source_key: str, stage: str, **params: Any) -> JobRecorder:
    await register_sources(session)
    return await JobRecorder.start(session, await source_id_for(session, source_key), stage, params)


def _raw_files(directory: Path, pattern: str) -> list[Path]:
    files = sorted(directory.glob(pattern))
    if not files:
        raise FileNotFoundError(
            f"No {pattern} in {directory}; run `python -m tastify_ml download` first"
        )
    return files


# --- listens ---------------------------------------------------------------------------------


async def stage_listens(force: bool = False, workers: int = 4) -> None:
    settings, paths = get_ml_settings(), Paths(get_ml_settings())
    if settings.listens_pseudonym_key is None:
        raise RuntimeError("Set LISTENS_PSEUDONYM_KEY in .env (any long random secret) first")
    key = settings.listens_pseudonym_key.get_secret_value().encode()
    dumps = _raw_files(paths.raw / "listenbrainz", "*.tar.zst")
    windows = await asyncio.gather(
        *(asyncio.to_thread(listenbrainz_listens.read_window, d) for d in dumps)
    )
    window = listenbrainz_listens.DumpWindow(
        min(w.start for w in windows), max(w.end for w in windows)
    )
    pending = [
        d
        for d in dumps
        if force or not (paths.listens / (d.name.removesuffix(".tar.zst") + ".parquet")).exists()
    ]
    async with SessionFactory() as session:
        job = await _start(
            session,
            "listenbrainz",
            "listens",
            files=[d.name for d in dumps],
            window=[window.start.isoformat(), window.end.isoformat()],
        )
        async with job:
            loop = asyncio.get_running_loop()
            with ProcessPoolExecutor(max_workers=min(workers, os.cpu_count() or 1)) as pool:
                results = await asyncio.gather(
                    *(
                        loop.run_in_executor(
                            pool, listenbrainz_listens.extract_dump, d, window, key, paths.listens
                        )
                        for d in pending
                    )
                )
            dropped: Counter[str] = Counter()
            for result in results:
                job.stats["lines"] += result["lines"]
                job.stats["kept"] += result["kept"]
                dropped.update(result["dropped"])
            for reason, count in dropped.items():
                job.stats[f"dropped_{reason}"] = count
            job.stats["files_processed"] = len(pending)
            await job.finish()


# --- mapping listens to recordings -------------------------------------------------------------


def _build_mapping(paths: Paths) -> dict[str, Any]:
    keys = unique_listen_keys(paths.listens)
    canonical = _raw_files(paths.raw / "musicbrainz_canonical", "*.tar.zst")[-1]
    logger.info("Mapping %d distinct listen keys against %s", len(keys), canonical.name)
    mapping = build_key_mapping(iter_canonical_batches(canonical), keys)
    pq.write_table(mapping, paths.key_mapping, compression="zstd")
    stats: Counter[str] = Counter(
        distinct_listen_keys=len(keys),
        mapped_keys=mapping.num_rows,
        ambiguous_keys=int(pc.sum(pc.greater(mapping["candidate_recordings"], 1)).as_py() or 0),
    )
    for path in listen_files(paths.listens):
        stats.update(map_listens(path, mapping, paths.mapped / path.name))
    popularity = recording_popularity(paths.mapped)
    pq.write_table(popularity, paths.popularity, compression="zstd")
    stats["recordings_heard"] = popularity.num_rows
    return {("unmapped" if k == "None" else k): v for k, v in stats.items()}


async def stage_mapping() -> None:
    paths = Paths(get_ml_settings())
    async with SessionFactory() as session:
        job = await _start(session, "musicbrainz_canonical", "mapping")
        async with job:
            job.stats.update(await asyncio.to_thread(_build_mapping, paths))
            await job.finish()


# --- genres and catalogue --------------------------------------------------------------------


async def stage_genres() -> None:
    async with SessionFactory() as session:
        job = await _start(session, "musicbrainz", "genres")
        async with job:
            writer = CatalogueWriter(session, await source_id_for(session, "musicbrainz"))
            await writer.load_genre_index()
            async with MusicBrainzClient(get_settings().metabrainz_user_agent) as client:
                genres = await client.all_genres()
            for genre in genres:
                await writer.ensure_genre(genre["name"], genre["id"])
            job.stats["genres"] = len(genres)
            await job.finish()


def select_seeds(popularity: pa.Table, size: int, min_listeners: int) -> list[str]:
    eligible = popularity.filter(pc.greater_equal(popularity["listeners"], min_listeners))
    return [str(m) for m in eligible["recording_mbid"].to_pylist()[:size]]


async def _cached_mbids(session: AsyncSession, source_id: Any) -> set[str]:
    rows = await session.scalars(
        select(RawRecord.external_id).where(
            RawRecord.source_id == source_id, RawRecord.entity_type == "recording"
        )
    )
    return set(rows.all())


async def stage_catalogue(
    size: int | None = None,
    min_listeners: int | None = None,
    batch_size: int = 500,
    refresh: bool = False,
) -> None:
    settings, paths = get_ml_settings(), Paths(get_ml_settings())
    size = size or settings.catalogue_size
    min_listeners = min_listeners or settings.catalogue_min_listeners
    seeds = select_seeds(pq.read_table(paths.popularity), size, min_listeners)
    async with SessionFactory() as session:
        job = await _start(
            session,
            "musicbrainz",
            "catalogue",
            size=size,
            min_listeners=min_listeners,
            refresh=refresh,
        )
        async with job:
            source_id = await source_id_for(session, "musicbrainz")
            async with ListenBrainzClient(get_settings().metabrainz_user_agent) as client:
                sitewide = [r["recording_mbid"] for r in await client.sitewide_top_recordings(1000)]
                known = set(seeds)
                seeds += [m for m in sitewide if m and m not in known]
                cached = set() if refresh else await _cached_mbids(session, source_id)
                to_fetch = [m for m in seeds if m not in cached]
                job.stats.update(seeds=len(seeds), cached=len(seeds) - len(to_fetch))
                for start in range(0, len(to_fetch), batch_size):
                    batch = to_fetch[start : start + batch_size]
                    payloads = await client.recording_metadata(batch)
                    for mbid, payload in payloads.items():
                        await store_raw_record(
                            session,
                            source_id=source_id,
                            entity_type="recording",
                            external_id=mbid,
                            payload=payload,
                            job_id=job.job_id,
                        )
                    job.stats["fetched"] += len(payloads)
                    await session.commit()
                    logger.info(
                        "Fetched metadata %d/%d",
                        min(start + batch_size, len(to_fetch)),
                        len(to_fetch),
                    )

            writer = CatalogueWriter(
                session,
                source_id,
                report_issue=lambda code, ref, message: job.error("resolution", code, ref, message),
            )
            await writer.load_genre_index()
            # All cached recordings: an IN list of seeds can exceed the driver's parameter limit.
            payload_rows = await session.execute(
                select(RawRecord.external_id, RawRecord.payload).where(
                    RawRecord.source_id == source_id, RawRecord.entity_type == "recording"
                )
            )
            payloads_by_mbid: dict[str, dict[str, Any]] = {
                row.external_id: row.payload for row in payload_rows
            }
            results = []
            for index, mbid in enumerate(seeds, start=1):
                cached_payload = payloads_by_mbid.get(mbid)
                if not cached_payload:
                    job.error(
                        "download", "metadata_not_found", mbid, "no metadata returned for recording"
                    )
                    continue
                try:
                    track = parse_recording(mbid, cached_payload)
                except (ValidationError, KeyError, TypeError) as exc:
                    job.error("validation", "invalid_recording", mbid, str(exc)[:500])
                    continue
                results.append(await writer.upsert_track(track))
                if index % COMMIT_EVERY == 0:
                    await job.flush()
                    await session.commit()
                    logger.info("Loaded %d/%d recordings", index, len(seeds))
            job.stats.update(outcome_counts(results))
            await job.finish()


# --- interactions ----------------------------------------------------------------------------


async def _mbid_to_track(session: AsyncSession) -> pa.Table:
    rows = (
        await session.execute(
            select(TrackExternalId.external_id, TrackExternalId.track_id).where(
                TrackExternalId.provider == "musicbrainz"
            )
        )
    ).all()
    return pa.table(
        {
            "recording_mbid": pa.array([r[0] for r in rows], pa.string()),
            "track_id": pa.array([str(r[1]) for r in rows], pa.string()),
        }
    )


def _write_interactions(paths: Paths, lookup: pa.Table) -> dict[str, int]:
    listens = mapped_listens(paths.mapped).to_table()
    joined = listens.join(lookup, "recording_mbid", join_type="inner")
    interactions = (
        joined.select(["user_key", "track_id", "listened_at"])
        .group_by(["user_key", "track_id", "listened_at"])
        .aggregate([])
        .sort_by([("listened_at", "ascending"), ("user_key", "ascending")])
    )
    pq.write_table(interactions, paths.interactions, compression="zstd")
    return {
        "mapped_listens": listens.num_rows,
        "interactions": interactions.num_rows,
        "users": len(pc.unique(interactions["user_key"])),
        "tracks": len(pc.unique(interactions["track_id"])),
    }


async def stage_interactions() -> None:
    paths = Paths(get_ml_settings())
    async with SessionFactory() as session:
        job = await _start(session, "listenbrainz", "interactions")
        async with job:
            lookup = await _mbid_to_track(session)
            job.stats.update(await asyncio.to_thread(_write_interactions, paths, lookup))
            await job.finish()


# --- audio features --------------------------------------------------------------------------


def first_per_track(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Several source records can resolve to one canonical track; keep the first one's features."""
    unique: dict[Any, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(row["track_id"], row)
    return list(unique.values())


async def _upsert_features(
    session: AsyncSession,
    rows: Sequence[dict[str, Any]],
    feature_source: str,
    feature_version: str,
    source_id: Any,
) -> None:
    rows = first_per_track(rows)
    for start in range(0, len(rows), COMMIT_EVERY):
        chunk = [
            {
                **row,
                "feature_source": feature_source,
                "feature_version": feature_version,
                "source_id": source_id,
            }
            for row in rows[start : start + COMMIT_EVERY]
        ]
        statement = insert(TrackFeatures).values(chunk)
        updatable = {
            c: statement.excluded[c]
            for c in chunk[0]
            if c not in ("track_id", "feature_source", "feature_version")
        }
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=["track_id", "feature_source", "feature_version"], set_=updatable
            )
        )
        await session.commit()


async def stage_acousticbrainz() -> None:
    paths = Paths(get_ml_settings())
    async with SessionFactory() as session:
        job = await _start(
            session, "acousticbrainz", "acousticbrainz", version=acousticbrainz.FEATURE_VERSION
        )
        async with job:
            lookup = await _mbid_to_track(session)
            files = {
                part: _raw_files(paths.raw / "acousticbrainz", f"*-{part}.tar.zst")[-1]
                for part in sources.ACOUSTICBRAINZ_PARTS
            }
            rhythm, lowlevel = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        acousticbrainz.read_part, files[part], part, lookup["recording_mbid"]
                    )
                    for part in sources.ACOUSTICBRAINZ_PARTS
                )
            )
            records = acousticbrainz.combine_features(rhythm, lowlevel)
            track_of = dict(
                zip(
                    lookup["recording_mbid"].to_pylist(),
                    lookup["track_id"].to_pylist(),
                    strict=True,
                )
            )
            by_track: dict[str, dict[str, Any]] = {}
            for record in records:
                track_id = track_of[str(record.pop("mbid"))]
                by_track.setdefault(track_id, {"track_id": track_id, **record})
            await _upsert_features(
                session,
                list(by_track.values()),
                "acousticbrainz",
                acousticbrainz.FEATURE_VERSION,
                await source_id_for(session, "acousticbrainz"),
            )
            job.stats.update(
                recordings_with_features=len(records), tracks_with_features=len(by_track)
            )
            await job.finish()


async def stage_fma(limit: int | None = None) -> None:
    paths = Paths(get_ml_settings())
    archive_path = _raw_files(paths.raw / "fma", "fma_metadata.zip")[0]
    archive = fma.open_metadata(archive_path)
    genres = {g.genre_id: g for g in fma.read_genres(archive)}
    echonest = await asyncio.to_thread(fma.read_echonest, archive)
    tracks = await asyncio.to_thread(fma.read_tracks, archive, echonest.index)
    if limit:
        tracks = tracks.iloc[:limit]
    async with SessionFactory() as session:
        job = await _start(session, "fma", "fma", tracks=len(tracks))
        async with job:
            source_id = await source_id_for(session, "fma")
            writer = CatalogueWriter(
                session,
                source_id,
                create_unknown_genres=True,
                report_issue=lambda code, ref, message: job.error("resolution", code, ref, message),
            )
            await writer.load_genre_index()
            genre_ids: dict[int, Any] = {}
            for genre in sorted(
                genres.values(), key=lambda g: (g.parent_id is not None, g.genre_id)
            ):
                parent = genre_ids.get(genre.parent_id) if genre.parent_id else None
                genre_ids[genre.genre_id] = await writer.ensure_genre(genre.title, parent_id=parent)
            await session.commit()

            results, features = [], []
            features_of = fma.echonest_by_track(echonest)
            for index, (track_id, row) in enumerate(fma.iter_rows(tracks), start=1):
                try:
                    source_track = fma.parse_track(track_id, row, genres)
                except (ValidationError, ValueError, KeyError, SyntaxError) as exc:
                    job.error("validation", "invalid_fma_track", str(track_id), str(exc)[:500])
                    continue
                result = await writer.upsert_track(source_track)
                results.append(result)
                values, rejected = fma.validate_features(features_of[track_id])
                for name in rejected:
                    job.error(
                        "validation",
                        "feature_out_of_range",
                        str(track_id),
                        f"{name} missing or out of range",
                    )
                features.append({"track_id": result.track_id, **values})
                if index % COMMIT_EVERY == 0:
                    await job.flush()
                    await session.commit()
                    logger.info("Loaded %d/%d FMA tracks", index, len(tracks))
            await session.commit()
            await _upsert_features(
                session, features, "fma_echonest", fma.FEATURE_VERSION, source_id
            )
            job.stats.update(outcome_counts(results))
            await job.finish()


# --- reset -----------------------------------------------------------------------------------

# Derived catalogue tables. Raw API payloads, provenance history and the genre vocabulary are kept,
# so a rebuild after a rule change needs no network access.
DERIVED_TABLES = (
    "track_features, track_genres, artist_genres, entity_match_candidates, track_external_ids, "
    "track_artists, tracks, album_external_ids, albums, artist_external_ids, artists"
)


async def stage_reset() -> None:
    async with SessionFactory() as session:
        await session.execute(text(f"TRUNCATE {DERIVED_TABLES}"))
        await session.commit()
    logger.info("Cleared derived catalogue tables (raw records and provenance kept)")


# --- quality ---------------------------------------------------------------------------------


async def stage_quality() -> bool:
    """Run the checks and write the report. Returns False if any error-severity check failed."""
    settings, paths = get_ml_settings(), Paths(get_ml_settings())
    async with SessionFactory() as session:
        results = await run_checks(session)
        summary = await collect_summary(session)
    report = write_report(
        summary, results, settings.reports_dir / "data-quality.md", paths.reports_history
    )
    failed = [r.check.name for r in results if r.blocking]
    logger.info("Data quality report written to %s", report)
    if failed:
        logger.error("Blocking data quality checks failed: %s", ", ".join(failed))
    return not failed


STAGES = (
    "listens",
    "mapping",
    "genres",
    "catalogue",
    "interactions",
    "acousticbrainz",
    "fma",
    "quality",
)
