"""Matching provider items to catalogue tracks, most reliable evidence first (ADR-014, ADR-018):

1. the MusicBrainz recording MBID (ListenBrainz's own mapping, or the one the client submitted);
2. the ISRC;
3. the exact artist-and-title matching key the catalogue is built with (accents, case,
   punctuation, featuring credits and remaster notes ignored; versions such as live or remix
   kept).

No fuzzy matching: an unmatched item is counted and skipped, never guessed.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Track, TrackExternalId
from app.domains.catalogue.normalization import normalize_isrc
from app.domains.catalogue.writer import track_matching_key
from app.domains.integrations.providers.base import ExternalItem


async def match_items(
    session: AsyncSession, items: Sequence[ExternalItem]
) -> list[uuid.UUID | None]:
    mbids = {i.recording_mbid.lower() for i in items if i.recording_mbid}
    isrcs = {code for i in items if (code := normalize_isrc(i.isrc))}
    keys = {track_matching_key(i.artist, i.title) for i in items}

    by_mbid: dict[str, uuid.UUID] = {}
    if mbids:
        rows = await session.execute(
            select(TrackExternalId.external_id, TrackExternalId.track_id).where(
                TrackExternalId.provider == "musicbrainz",
                TrackExternalId.external_id.in_(mbids),
            )
        )
        by_mbid = {str(mbid).lower(): track for mbid, track in rows.all()}

    by_isrc: dict[str, uuid.UUID] = {}
    if isrcs:
        rows = await session.execute(
            select(Track.isrc, Track.id).where(Track.isrc.in_(isrcs)).order_by(Track.id)
        )
        for isrc, isrc_track in rows.all():
            by_isrc.setdefault(str(isrc), isrc_track)

    by_key: dict[str, uuid.UUID] = {}
    if keys:
        rows = await session.execute(
            select(Track.matching_key, Track.id)
            .where(Track.matching_key.in_(keys))
            .order_by(Track.id)
        )
        for key, key_track in rows.all():
            by_key.setdefault(str(key), key_track)

    matched: list[uuid.UUID | None] = []
    for item in items:
        track: uuid.UUID | None = None
        if item.recording_mbid:
            track = by_mbid.get(item.recording_mbid.lower())
        if track is None and (code := normalize_isrc(item.isrc)):
            track = by_isrc.get(code)
        if track is None:
            track = by_key.get(track_matching_key(item.artist, item.title))
        matched.append(track)
    return matched
