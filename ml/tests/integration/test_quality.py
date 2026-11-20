from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.ingestion import SourceArtist, SourceCredit, SourceGenreTag, SourceTrack
from app.domains.catalogue.provenance import ensure_data_source
from app.domains.catalogue.writer import CatalogueWriter
from soniqueo_ml.data.quality.checks import run_checks
from soniqueo_ml.data.quality.report import collect_summary, render_markdown, write_report

pytestmark = pytest.mark.integration


def track(
    external_id: str, title: str, *, genres: list[str], duration_ms: int | None
) -> SourceTrack:
    return SourceTrack(
        provider="musicbrainz",
        external_id=external_id,
        title=title,
        credits=[
            SourceCredit(
                artist=SourceArtist(
                    provider="musicbrainz", external_id=f"artist-{external_id}", name="Artist"
                ),
                credited_name="Artist",
            )
        ],
        duration_ms=duration_ms,
        genres=[SourceGenreTag(name=g) for g in genres],
    )


async def seeded(session: AsyncSession) -> CatalogueWriter:
    source_id = await ensure_data_source(
        session,
        key="musicbrainz",
        name="MusicBrainz",
        homepage_url="https://musicbrainz.org",
        license="CC0-1.0",
        license_url="https://creativecommons.org/publicdomain/zero/1.0/",
        usage_restriction="non_commercial",
    )
    writer = CatalogueWriter(session, source_id)
    await writer.ensure_genre("pop")
    return writer


async def test_a_clean_catalogue_passes_every_error_check(session: AsyncSession) -> None:
    writer = await seeded(session)
    await writer.upsert_track(
        track("6f33dc05-cdc0-4a2f-8039-e8fed082eec6", "Song", genres=["pop"], duration_ms=200_000)
    )
    await session.commit()

    results = {r.check.name: r for r in await run_checks(session)}

    assert not [name for name, r in results.items() if r.blocking]
    assert results["tracks_without_genres"].passed
    assert results["missing_duration"].passed


async def test_checks_detect_incomplete_and_broken_records(session: AsyncSession) -> None:
    writer = await seeded(session)
    await writer.upsert_track(track("not-a-uuid", "No Genre", genres=[], duration_ms=None))
    orphan = await writer.upsert_track(
        track("9c4d04a6-b97d-46c8-bc49-2a3090737078", "Orphan", genres=["pop"], duration_ms=180_000)
    )
    await session.execute(
        text("DELETE FROM track_external_ids WHERE track_id = :id"), {"id": orphan.track_id}
    )
    await session.execute(
        text("UPDATE tracks SET release_year = :year WHERE id = :id"),
        {"year": datetime.now(UTC).year + 5, "id": orphan.track_id},
    )
    await session.commit()

    results = {r.check.name: r for r in await run_checks(session)}

    assert results["tracks_without_genres"].count == 1
    assert results["missing_duration"].count == 1
    assert results["invalid_musicbrainz_ids"].blocking
    assert results["tracks_without_identifiers"].blocking
    assert results["implausible_release_years"].blocking
    assert results["tracks_without_identifiers"].samples[0]["title"] == "Orphan"


async def test_report_summarises_the_catalogue(session: AsyncSession, tmp_path: Path) -> None:
    writer = await seeded(session)
    await writer.upsert_track(
        track("6f33dc05-cdc0-4a2f-8039-e8fed082eec6", "Song", genres=["pop"], duration_ms=200_000)
    )
    await session.commit()
    results = await run_checks(session)
    summary = await collect_summary(session)

    path = write_report(summary, results, tmp_path / "report.md", tmp_path / "history")

    markdown = path.read_text(encoding="utf-8")
    assert summary["tracks"] == 1
    assert "| Tracks | 1 |" in markdown
    assert "| musicbrainz | CC0-1.0 | non_commercial |" in markdown
    assert len(list((tmp_path / "history").glob("*.json"))) == 1
    assert render_markdown(summary, results, datetime.now(UTC)).startswith(
        "# Catalogue data quality"
    )
