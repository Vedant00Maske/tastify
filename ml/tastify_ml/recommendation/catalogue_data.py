"""Loads the catalogue from PostgreSQL into in-memory frames for model training and evaluation.

The served catalogue excludes research-only sources (FMA, ADR-013): those tracks are only used by
the separate FMA experiment, which loads them explicitly with `research_only=True`.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.recommendations.ranking import GENRE_PRIOR_VOTES

FEATURE_COLUMNS = (
    "tempo",
    "energy",
    "danceability",
    "valence",
    "acousticness",
    "instrumentalness",
    "loudness",
    "onset_rate",
)

_TRACKS_SQL = """
SELECT t.id::text AS track_id, t.artist_id::text AS artist_id, t.title, a.name AS artist_name,
       t.matching_key, t.release_year, t.duration_ms, nullif(al.album_type, '') AS album_type,
       a.area AS artist_area, a.artist_type, s.key AS source
FROM tracks t
JOIN artists a ON a.id = t.artist_id
LEFT JOIN albums al ON al.id = t.album_id
JOIN data_sources s ON s.id = t.source_id
WHERE (s.usage_restriction = 'research_only') = :research_only
ORDER BY t.id
"""

# Genre votes with the total votes of the same (track or artist, source, level), so tag weights
# can be smoothed (ranking.smoothed_tag_weight). The artist's own genres form a third level; their
# totals are computed per artist before joining tracks.
_GENRES_SQL = """
SELECT tg.track_id::text AS track_id, g.name AS genre, tg.level, tg.source_id::text AS source,
       tg.vote_count AS votes,
       sum(tg.vote_count) OVER (PARTITION BY tg.track_id, tg.source_id, tg.level) AS total
FROM track_genres tg JOIN genres g ON g.id = tg.genre_id
UNION ALL
SELECT t.id::text, ag.genre, 'artist', ag.source, ag.votes, ag.total
FROM (
    SELECT a.artist_id, g.name AS genre, a.source_id::text AS source, a.vote_count AS votes,
           sum(a.vote_count) OVER (PARTITION BY a.artist_id, a.source_id) AS total
    FROM artist_genres a JOIN genres g ON g.id = a.genre_id
) ag
JOIN tracks t ON t.artist_id = ag.artist_id
"""

# Column names are module constants, not input.
_FEATURES_SQL = (
    "SELECT track_id::text AS track_id, feature_source, "  # noqa: S608
    + ", ".join(FEATURE_COLUMNS)
    + " FROM track_features"
)


@dataclass
class CatalogueData:
    """Tracks in a fixed order: a track's row position is its item index everywhere."""

    tracks: pd.DataFrame
    # item, genre, level, source, votes, total (votes of that item, source and level)
    genres: pd.DataFrame
    # item, then one column per observed "<feature_source>_<feature>" (NaN when missing)
    features: pd.DataFrame

    @property
    def n_items(self) -> int:
        return len(self.tracks)

    @property
    def track_ids(self) -> np.ndarray:
        return self.tracks["track_id"].to_numpy()

    def tag_weights(self, prior: float = GENRE_PRIOR_VOTES) -> pd.DataFrame:
        """item, genre, level, weight: smoothed vote share, strongest source per level."""
        genres = self.genres
        weights = genres["votes"].to_numpy(dtype=float) / (
            genres["total"].to_numpy(dtype=float) + prior
        )
        return (
            genres.assign(weight=weights)
            .groupby(["item", "genre", "level"], observed=True, sort=False)["weight"]
            .max()
            .reset_index()
        )

    def item_index(self) -> dict[str, int]:
        return {track_id: i for i, track_id in enumerate(self.tracks["track_id"])}

    def artist_codes(self) -> np.ndarray:
        """Integer code of each item's primary artist."""
        codes, _ = pd.factorize(self.tracks["artist_id"])
        return np.asarray(codes)


def _frame(rows: list[tuple[object, ...]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame.from_records(rows, columns=columns)


async def load_catalogue(session: AsyncSession, research_only: bool = False) -> CatalogueData:
    result = await session.execute(text(_TRACKS_SQL), {"research_only": research_only})
    tracks = _frame([tuple(r) for r in result], list(result.keys()))
    index = pd.Series(np.arange(len(tracks)), index=tracks["track_id"])

    result = await session.execute(text(_GENRES_SQL))
    genres = _frame([tuple(r) for r in result], list(result.keys()))
    genres = genres[genres["track_id"].isin(index.index)]
    genres = genres.assign(item=index.loc[genres["track_id"]].to_numpy()).drop(columns="track_id")

    result = await session.execute(text(_FEATURES_SQL))
    raw = _frame([tuple(r) for r in result], list(result.keys()))
    raw = raw[raw["track_id"].isin(index.index)]
    features = pd.DataFrame({"item": np.arange(len(tracks))})
    for source, group in raw.groupby("feature_source"):
        group = group.drop_duplicates("track_id")
        values = group[list(FEATURE_COLUMNS)].astype(float)
        observed = [c for c in FEATURE_COLUMNS if values[c].notna().any()]
        block = values[observed].add_prefix(f"{source}_")
        block.insert(0, "item", index.loc[group["track_id"]].to_numpy())
        features = features.merge(block, on="item", how="left")
    for column in ("release_year", "duration_ms"):
        tracks[column] = pd.to_numeric(tracks[column], errors="coerce")
    return CatalogueData(
        tracks=tracks.reset_index(drop=True),
        genres=genres.reset_index(drop=True),
        features=features,
    )
