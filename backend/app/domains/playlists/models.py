"""User playlists (spec §6.2: Playlist, PlaylistTrack; Milestone 4).

A playlist is `manual` (the user picks the tracks) or `generated` (saved from a recommendation
collection: for you, a mood, hidden gems, a genre, an artist radio). A generated playlist keeps
the parameters it was made with in `generator`, so it can be regenerated; those parameters vary by
collection, which is why they are JSONB (spec §6.4 rule 10).
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.domains.catalogue.models import created_at_column, updated_at_column, uuid_pk

PLAYLIST_KINDS = ("manual", "generated")
COLLECTIONS = ("for_you", "mood", "hidden_gems", "genre", "artist_radio")
MAX_TRACKS = 500
MAX_PLAYLISTS = 200


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Playlist(Base):
    __tablename__ = "playlists"
    __table_args__ = (
        CheckConstraint(_in("kind", PLAYLIST_KINDS), name="kind_valid"),
        CheckConstraint(
            f"collection IS NULL OR {_in('collection', COLLECTIONS)}", name="collection_valid"
        ),
        Index("ix_playlists_user_id_created_at", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    collection: Mapped[str | None] = mapped_column(String(32))
    generator: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class PlaylistTrack(Base):
    __tablename__ = "playlist_tracks"
    __table_args__ = (Index("ix_playlist_tracks_playlist_id_position", "playlist_id", "position"),)

    playlist_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("playlists.id", ondelete="CASCADE"), primary_key=True
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracks.id", ondelete="RESTRICT"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
