"""Small synthetic catalogues and listening logs for recommendation tests."""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from tastify_ml.recommendation.catalogue_data import CatalogueData

T0 = pd.Timestamp("2026-11-01", tz="UTC")


def make_catalogue(
    tracks: Sequence[dict[str, object]],
    genres: Sequence[tuple[int, str, str, int, int]] = (),
    features: dict[str, Sequence[float | None]] | None = None,
) -> CatalogueData:
    """tracks: dicts with at least track_id and artist_id.

    genres: (item, genre, level, votes, total votes of that item and level), from one source."""
    defaults: dict[str, object] = {
        "title": "Song",
        "artist_name": "Artist",
        "release_year": None,
        "duration_ms": 200_000,
        "album_type": None,
        "artist_area": None,
        "artist_type": None,
        "source": "musicbrainz",
    }
    rows = [{**defaults, "matching_key": f"{t['artist_id']}|{t['track_id']}", **t} for t in tracks]
    frame = pd.DataFrame(rows)
    frame["release_year"] = pd.to_numeric(frame["release_year"], errors="coerce")
    frame["duration_ms"] = pd.to_numeric(frame["duration_ms"], errors="coerce")
    feature_frame = pd.DataFrame({"item": np.arange(len(frame))})
    for name, values in (features or {}).items():
        feature_frame[name] = pd.array(values, dtype="Float64").to_numpy(
            dtype=float, na_value=np.nan
        )
    return CatalogueData(
        tracks=frame,
        genres=pd.DataFrame(genres, columns=["item", "genre", "level", "votes", "total"]).assign(
            source="musicbrainz"
        ),
        features=feature_frame,
    )


def listens(rows: Sequence[tuple[str, str, float]]) -> pd.DataFrame:
    """(user_key, track_id, days after T0) -> interactions frame."""
    return pd.DataFrame(
        {
            "user_key": [r[0] for r in rows],
            "track_id": [r[1] for r in rows],
            "listened_at": pd.to_datetime([T0 + pd.Timedelta(days=r[2]) for r in rows], utc=True),
        }
    )
