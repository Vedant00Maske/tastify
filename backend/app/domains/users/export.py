"""Data export (spec §12.4): everything TASTIFY stores about one user, as plain JSON.

Includes the account (never the password hash), declared preferences, every interaction event,
the derived taste profile and every playlist with its tracks. Sessions are listed without their
token hashes.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.playlists.models import Playlist, PlaylistTrack
from app.domains.users.models import User, UserInteraction, UserSession, UserTasteProfile
from app.domains.users.service import UserService

EXPORT_VERSION = 1


async def export_user_data(session: AsyncSession, user: User) -> dict[str, Any]:
    preferences = await UserService(session).preferences(user.id)
    events = (
        await session.scalars(
            select(UserInteraction)
            .where(UserInteraction.user_id == user.id)
            .order_by(UserInteraction.occurred_at, UserInteraction.id)
        )
    ).all()
    profile = await session.get(UserTasteProfile, user.id)
    playlists = (
        await session.scalars(
            select(Playlist).where(Playlist.user_id == user.id).order_by(Playlist.created_at)
        )
    ).all()
    playlist_tracks: dict[Any, list[dict[str, Any]]] = {}
    if playlists:
        rows = await session.execute(
            select(PlaylistTrack)
            .where(PlaylistTrack.playlist_id.in_([p.id for p in playlists]))
            .order_by(PlaylistTrack.playlist_id, PlaylistTrack.position)
        )
        for (track,) in rows:
            playlist_tracks.setdefault(track.playlist_id, []).append(
                {"track_id": track.track_id, "position": track.position, "added_at": track.added_at}
            )
    sessions = (
        await session.scalars(select(UserSession).where(UserSession.user_id == user.id))
    ).all()
    return {
        "export_version": EXPORT_VERSION,
        "exported_at": datetime.now(UTC),
        "account": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
            "created_at": user.created_at,
            "terms_accepted_at": user.terms_accepted_at,
            "onboarding_completed_at": user.onboarding_completed_at,
            "last_login_at": user.last_login_at,
        },
        "preferences": preferences.model_dump(mode="json"),
        "interactions": [
            {
                "id": e.id,
                "track_id": e.track_id,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at,
                "received_at": e.received_at,
                "position_ms": e.position_ms,
                "session_id": e.session_id,
                "source": e.source,
                "client_event_id": e.client_event_id,
            }
            for e in events
        ],
        "taste_profile": None
        if profile is None
        else {
            "profile_version": profile.profile_version,
            "genre_affinity": profile.genre_affinity,
            "artist_affinity": profile.artist_affinity,
            "negative_artists": profile.negative_artists,
            "known_artists": profile.known_artists,
            "listening_stats": profile.listening_stats,
            "exploration_preference": profile.exploration_preference,
            "updated_at": profile.updated_at,
        },
        "playlists": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "kind": p.kind,
                "collection": p.collection,
                "generator": p.generator,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
                "tracks": playlist_tracks.get(p.id, []),
            }
            for p in playlists
        ],
        "sessions": [
            {
                "created_at": s.created_at,
                "last_seen_at": s.last_seen_at,
                "expires_at": s.expires_at,
                "revoked_at": s.revoked_at,
                "user_agent": s.user_agent,
            }
            for s in sessions
        ],
    }
