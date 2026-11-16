import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.ingestion import (
    SourceAlbum,
    SourceArtist,
    SourceCredit,
    SourceGenreTag,
    SourceTrack,
)
from app.domains.catalogue.models import (
    EntityMatchCandidate,
    Track,
    TrackExternalId,
    TrackGenre,
)
from app.domains.catalogue.writer import CatalogueWriter, WriteOutcome
from tests.integration.catalogue.conftest import register_source

pytestmark = pytest.mark.integration

BEYONCE_MB = SourceArtist(provider="musicbrainz", external_id="mb-artist-1", name="Beyoncé")


def mb_track(
    mbid: str = "mb-rec-1",
    *,
    duration_ms: int = 261_000,
    isrcs: list[str] | None = None,
    **extra: object,
) -> SourceTrack:
    return SourceTrack(
        provider="musicbrainz",
        external_id=mbid,
        title="Halo",
        credits=[SourceCredit(artist=BEYONCE_MB, credited_name="Beyoncé")],
        duration_ms=duration_ms,
        isrcs=["USSM10804556"] if isrcs is None else isrcs,
        album=SourceAlbum(
            provider="musicbrainz", external_id="mb-rg-1", title="I Am... Sasha Fierce"
        ),
        release_date="2008-11-12",
        **extra,  # type: ignore[arg-type]
    )


def fma_track(fma_id: str = "fma-1", *, duration_ms: int = 262_000) -> SourceTrack:
    return SourceTrack(
        provider="fma",
        external_id=fma_id,
        title="Halo (feat. Nobody)",
        credits=[
            SourceCredit(
                artist=SourceArtist(provider="fma", external_id="fma-artist-9", name="Beyonce"),
                credited_name="Beyonce",
            )
        ],
        duration_ms=duration_ms,
    )


async def external_ids(db: AsyncSession, track_id: object) -> set[tuple[str, str]]:
    rows = await db.execute(
        select(TrackExternalId.provider, TrackExternalId.external_id).where(
            TrackExternalId.track_id == track_id
        )
    )
    return {(provider, external_id) for provider, external_id in rows}


async def test_records_from_two_sources_resolve_to_one_canonical_track(
    session: AsyncSession,
) -> None:
    mb_writer = CatalogueWriter(session, await register_source(session, "musicbrainz"))
    fma_writer = CatalogueWriter(session, await register_source(session, "fma"))

    created = await mb_writer.upsert_track(mb_track())
    linked = await fma_writer.upsert_track(fma_track())

    assert created.outcome is WriteOutcome.CREATED
    assert linked.outcome is WriteOutcome.LINKED
    assert linked.track_id == created.track_id
    assert await external_ids(session, created.track_id) == {
        ("musicbrainz", "mb-rec-1"),
        ("isrc", "USSM10804556"),
        ("fma", "fma-1"),
    }
    assert await session.scalar(select(func.count()).select_from(Track)) == 1


async def test_reingesting_the_same_record_is_idempotent(session: AsyncSession) -> None:
    writer = CatalogueWriter(session, await register_source(session, "musicbrainz"))

    first = await writer.upsert_track(mb_track())
    second = await writer.upsert_track(mb_track())

    assert second.outcome is WriteOutcome.UPDATED
    assert second.track_id == first.track_id
    assert await session.scalar(select(func.count()).select_from(Track)) == 1


async def test_matching_isrc_links_a_differently_titled_record(session: AsyncSession) -> None:
    writer = CatalogueWriter(session, await register_source(session, "musicbrainz"))
    original = await writer.upsert_track(mb_track())

    variant = mb_track("mb-rec-2").model_copy(update={"title": "Halo (Album Version)"})
    result = await writer.upsert_track(variant)

    assert result.outcome is WriteOutcome.LINKED
    assert result.track_id == original.track_id
    assert result.match is not None
    assert result.match.method == "isrc"


async def test_ambiguous_match_creates_a_separate_track_for_review(session: AsyncSession) -> None:
    mb = CatalogueWriter(session, await register_source(session, "musicbrainz"))
    short = await mb.upsert_track(mb_track("mb-rec-1", duration_ms=260_000, isrcs=[]))
    long = await mb.upsert_track(mb_track("mb-rec-2", duration_ms=264_500, isrcs=[]))
    assert long.track_id != short.track_id  # 4.5 s apart: different recordings

    fma = CatalogueWriter(session, await register_source(session, "fma"))
    result = await fma.upsert_track(fma_track(duration_ms=262_200))  # within 3 s of both

    assert result.outcome is WriteOutcome.CREATED_FOR_REVIEW
    candidates = (
        await session.scalars(
            select(EntityMatchCandidate.candidate_track_id).where(
                EntityMatchCandidate.track_id == result.track_id
            )
        )
    ).all()
    assert set(candidates) == {short.track_id, long.track_id}


async def test_identifier_owned_by_another_track_is_reported_not_moved(
    session: AsyncSession,
) -> None:
    issues: list[tuple[str, str, str]] = []
    writer = CatalogueWriter(
        session,
        await register_source(session, "musicbrainz"),
        report_issue=lambda code, ref, message: issues.append((code, ref, message)),
    )
    await writer.upsert_track(mb_track())
    other = mb_track("mb-rec-9").model_copy(
        update={"title": "Single Ladies", "isrcs": ["USSM10804556"], "duration_ms": 400_000}
    )

    result = await writer.upsert_track(other)

    assert result.outcome is WriteOutcome.CREATED_FOR_REVIEW
    assert [code for code, _, _ in issues] == ["identifier_conflict"]
    created = await session.get(Track, result.track_id)
    assert created is not None
    assert created.isrc is None  # the conflicting ISRC is not adopted as this track's ISRC


async def test_genre_votes_become_normalized_weights(session: AsyncSession) -> None:
    writer = CatalogueWriter(session, await register_source(session, "musicbrainz"))
    pop = await writer.ensure_genre("pop")
    rnb = await writer.ensure_genre("r&b")
    track = mb_track(
        genres=[
            SourceGenreTag(name="Pop", count=3),
            SourceGenreTag(name="R&B", count=1),
            SourceGenreTag(name="2000s", count=5),  # not a genre: ignored
        ]
    )

    result = await writer.upsert_track(track)

    rows = await session.execute(
        select(TrackGenre.genre_id, TrackGenre.weight).where(TrackGenre.track_id == result.track_id)
    )
    assert dict(rows.all()) == {pop: 0.75, rnb: 0.25}


async def test_linking_a_second_record_merges_genre_votes(session: AsyncSession) -> None:
    writer = CatalogueWriter(session, await register_source(session, "musicbrainz"))
    pop = await writer.ensure_genre("pop")
    rnb = await writer.ensure_genre("r&b")
    first = await writer.upsert_track(mb_track(genres=[SourceGenreTag(name="pop", count=1)]))

    second = await writer.upsert_track(
        mb_track("mb-rec-2", genres=[SourceGenreTag(name="r&b", count=1)])
    )

    assert second.outcome is WriteOutcome.LINKED
    rows = await session.execute(
        select(TrackGenre.genre_id, TrackGenre.weight, TrackGenre.vote_count).where(
            TrackGenre.track_id == first.track_id
        )
    )
    assert {genre: (weight, votes) for genre, weight, votes in rows} == {
        pop: (0.5, 1),
        rnb: (0.5, 1),
    }
