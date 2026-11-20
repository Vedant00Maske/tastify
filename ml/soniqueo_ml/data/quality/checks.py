"""Data quality checks over the catalogue.

Severity:
- error:   the catalogue is wrong (broken relationships, invalid values). Fails the pipeline.
- warning: data is incomplete or suspicious and should be looked at.
- info:    a measurement worth tracking over time.

Hard rules that the schema already enforces (foreign keys, CHECK constraints on durations, ISRC
format and feature ranges) are re-checked here defensively, so a relaxed constraint can't hide a
regression.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Check:
    name: str
    category: str
    severity: Severity
    description: str
    sql: str
    """Selects the offending rows; the first column identifies each one."""


@dataclass
class CheckResult:
    check: Check
    count: int
    samples: list[dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.count == 0

    @property
    def blocking(self) -> bool:
        return self.check.severity is Severity.ERROR and not self.passed


CHECKS: tuple[Check, ...] = (
    Check(
        "tracks_without_identifiers",
        "missing track ids",
        Severity.ERROR,
        "Tracks with no provider identifier at all (cannot be traced to a source).",
        """SELECT t.id, t.title FROM tracks t
           WHERE NOT EXISTS (SELECT 1 FROM track_external_ids e WHERE e.track_id = t.id)""",
    ),
    Check(
        "tracks_missing_title",
        "missing track ids",
        Severity.ERROR,
        "Tracks with an empty title or matching key.",
        "SELECT id, title FROM tracks WHERE btrim(title) = '' OR matching_key = '' OR matching_key = '|'",
    ),
    Check(
        "unresolved_duplicates",
        "duplicate tracks",
        Severity.WARNING,
        "Possible duplicates the resolution policy refused to link automatically (pending review).",
        """SELECT c.track_id, c.candidate_track_id, c.method, c.confidence
           FROM entity_match_candidates c WHERE c.status = 'pending'""",
    ),
    Check(
        "same_key_same_duration",
        "duplicate tracks",
        Severity.WARNING,
        "Distinct tracks sharing artist/title key and duration within 1 s, with no review record.",
        """SELECT a.id, b.id AS other_id, a.matching_key FROM tracks a
           JOIN tracks b ON a.matching_key = b.matching_key AND a.id < b.id
             AND abs(a.duration_ms - b.duration_ms) <= 1000
           WHERE NOT EXISTS (
             SELECT 1 FROM entity_match_candidates c
             WHERE (c.track_id, c.candidate_track_id) IN ((a.id, b.id), (b.id, a.id)))""",
    ),
    Check(
        "tracks_without_credits",
        "invalid artist relationships",
        Severity.ERROR,
        "Tracks with no artist credit rows.",
        """SELECT t.id, t.title FROM tracks t
           WHERE NOT EXISTS (SELECT 1 FROM track_artists ta WHERE ta.track_id = t.id)""",
    ),
    Check(
        "primary_artist_not_first_credit",
        "invalid artist relationships",
        Severity.ERROR,
        "Tracks whose primary artist differs from the first credited artist.",
        """SELECT t.id, t.title FROM tracks t
           JOIN track_artists ta ON ta.track_id = t.id AND ta.position = 0
           WHERE ta.artist_id <> t.artist_id""",
    ),
    Check(
        "artists_without_tracks",
        "invalid artist relationships",
        Severity.INFO,
        "Artists not credited on any track (e.g. only referenced by albums).",
        """SELECT a.id, a.name FROM artists a
           WHERE NOT EXISTS (SELECT 1 FROM track_artists ta WHERE ta.artist_id = a.id)""",
    ),
    Check(
        "implausible_release_years",
        "invalid timestamps",
        Severity.ERROR,
        "Release years before 1000 or more than a year in the future.",
        """SELECT id, release_date, release_year FROM tracks
           WHERE release_year < 1000 OR release_year > extract(year FROM current_date) + 1
           UNION ALL
           SELECT id, release_date, release_year FROM albums
           WHERE release_year < 1000 OR release_year > extract(year FROM current_date) + 1""",
    ),
    Check(
        "announced_future_releases",
        "invalid timestamps",
        Severity.WARNING,
        "Release dates later than today (announced releases already being streamed).",
        """SELECT id, title, release_date FROM tracks WHERE release_date > current_date
           UNION ALL
           SELECT id, title, release_date FROM albums WHERE release_date > current_date""",
    ),
    Check(
        "track_released_before_artist_began",
        "invalid timestamps",
        Severity.WARNING,
        "Tracks released more than a year before their artist's begin year.",
        """SELECT t.id, t.release_year, a.begin_year FROM tracks t JOIN artists a ON a.id = t.artist_id
           WHERE t.release_year < a.begin_year - 1""",
    ),
    Check(
        "invalid_duration",
        "invalid duration",
        Severity.ERROR,
        "Durations outside 1 s to 3 h (also enforced by a CHECK constraint).",
        "SELECT id, duration_ms FROM tracks WHERE duration_ms NOT BETWEEN 1000 AND 10800000",
    ),
    Check(
        "missing_duration",
        "invalid duration",
        Severity.WARNING,
        "Tracks without a duration (weakens entity resolution).",
        "SELECT id, title FROM tracks WHERE duration_ms IS NULL",
    ),
    Check(
        "tracks_without_genres",
        "missing genre information",
        Severity.WARNING,
        "Tracks with no genre at track, album or artist level.",
        """SELECT t.id, t.title FROM tracks t
           WHERE NOT EXISTS (SELECT 1 FROM track_genres g WHERE g.track_id = t.id)
             AND NOT EXISTS (SELECT 1 FROM artist_genres g WHERE g.artist_id = t.artist_id)""",
    ),
    Check(
        "identifier_conflicts",
        "inconsistent provider identifiers",
        Severity.WARNING,
        "Identifiers a source asserted for a track but already owned by another track "
        "(latest run of each stage).",
        """SELECT e.record_ref, e.message FROM ingestion_errors e
           WHERE e.error_code = 'identifier_conflict' AND e.job_id IN (
             SELECT DISTINCT ON (stage, source_id) id FROM ingestion_jobs
             ORDER BY stage, source_id, started_at DESC)""",
    ),
    Check(
        "primary_isrc_not_registered",
        "inconsistent provider identifiers",
        Severity.ERROR,
        "tracks.isrc values missing from track_external_ids.",
        """SELECT t.id, t.isrc FROM tracks t WHERE t.isrc IS NOT NULL AND NOT EXISTS (
             SELECT 1 FROM track_external_ids e
             WHERE e.track_id = t.id AND e.provider = 'isrc' AND e.external_id = t.isrc)""",
    ),
    Check(
        "invalid_isrc_identifiers",
        "inconsistent provider identifiers",
        Severity.ERROR,
        "ISRC identifiers not in canonical 12-character form.",
        """SELECT track_id, external_id FROM track_external_ids
           WHERE provider = 'isrc' AND external_id !~ '^[A-Z]{2}[A-Z0-9]{3}[0-9]{7}$'""",
    ),
    Check(
        "invalid_musicbrainz_ids",
        "inconsistent provider identifiers",
        Severity.ERROR,
        "MusicBrainz identifiers that are not UUIDs.",
        """SELECT track_id, external_id FROM track_external_ids
           WHERE provider = 'musicbrainz'
             AND external_id !~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'""",
    ),
    Check(
        "features_out_of_range",
        "incorrect feature ranges",
        Severity.ERROR,
        "Unit-scale features outside [0, 1] or tempo outside 20-300 BPM.",
        """SELECT track_id, feature_source FROM track_features
           WHERE greatest(energy, danceability, valence, acousticness, instrumentalness, loudness) > 1
              OR least(energy, danceability, valence, acousticness, instrumentalness, loudness) < 0
              OR tempo NOT BETWEEN 20 AND 300 OR onset_rate < 0""",
    ),
    Check(
        "suspicious_tempo",
        "incorrect feature ranges",
        Severity.INFO,
        "Tempo outside the common 50-220 BPM range (often half/double-time detection).",
        "SELECT track_id, tempo FROM track_features WHERE tempo NOT BETWEEN 50 AND 220",
    ),
    Check(
        "genre_weights_not_normalized",
        "incorrect feature ranges",
        Severity.ERROR,
        "Per track/source/level genre weights that do not sum to 1.",
        """SELECT track_id, source_id, level, sum(weight) AS total FROM track_genres
           GROUP BY track_id, source_id, level HAVING abs(sum(weight) - 1) > 0.001""",
    ),
)

SAMPLE_SIZE = 5


async def run_check(session: AsyncSession, check: Check) -> CheckResult:
    count = await session.scalar(text(f"SELECT count(*) FROM ({check.sql}) AS offending"))  # noqa: S608
    samples: list[dict[str, Any]] = []
    if count:
        rows = await session.execute(text(f"{check.sql} LIMIT {SAMPLE_SIZE}"))  # noqa: S608
        samples = [{key: _jsonable(value) for key, value in row._mapping.items()} for row in rows]
    return CheckResult(check, int(count or 0), samples)


async def run_checks(session: AsyncSession, checks: tuple[Check, ...] = CHECKS) -> list[CheckResult]:
    return [await run_check(session, check) for check in checks]


def _jsonable(value: Any) -> Any:
    return value if isinstance(value, int | float | str | bool | type(None)) else str(value)
