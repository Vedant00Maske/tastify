"""Data quality report: catalogue summary, provenance, pipeline runs and check results."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from soniqueo_ml.data.quality.checks import CheckResult, Severity

SUMMARY_QUERIES = {
    "tracks": "SELECT count(*) FROM tracks",
    "artists": "SELECT count(*) FROM artists",
    "albums": "SELECT count(*) FROM albums",
    "genres": "SELECT count(*) FROM genres",
    "tracks_with_isrc": "SELECT count(*) FROM tracks WHERE isrc IS NOT NULL",
    "tracks_with_duration": "SELECT count(*) FROM tracks WHERE duration_ms IS NOT NULL",
    "tracks_with_track_or_album_genres": "SELECT count(DISTINCT track_id) FROM track_genres",
    "tracks_with_any_genre": """SELECT count(*) FROM tracks t
        WHERE EXISTS (SELECT 1 FROM track_genres g WHERE g.track_id = t.id)
           OR EXISTS (SELECT 1 FROM artist_genres g WHERE g.artist_id = t.artist_id)""",
    "tracks_with_audio_features": "SELECT count(DISTINCT track_id) FROM track_features",
    "tracks_in_multiple_sources": """SELECT count(*) FROM (
        SELECT track_id FROM track_external_ids WHERE provider <> 'isrc'
        GROUP BY track_id HAVING count(DISTINCT provider) > 1) AS multi""",
    "pending_match_reviews": "SELECT count(*) FROM entity_match_candidates WHERE status = 'pending'",
}
BREAKDOWN_QUERIES = {
    "identifiers_by_provider": """SELECT provider, match_method, count(*) FROM track_external_ids
        GROUP BY provider, match_method ORDER BY provider, match_method""",
    "tracks_by_source": """SELECT s.key, count(*) FROM tracks t JOIN data_sources s ON s.id = t.source_id
        GROUP BY s.key ORDER BY s.key""",
    "features_by_source": """SELECT feature_source, feature_version, count(*) FROM track_features
        GROUP BY feature_source, feature_version ORDER BY feature_source""",
    "top_genres": """SELECT g.name, count(DISTINCT tg.track_id) FROM track_genres tg
        JOIN genres g ON g.id = tg.genre_id GROUP BY g.name ORDER BY 2 DESC LIMIT 15""",
}


async def collect_summary(session: AsyncSession) -> dict[str, Any]:
    summary: dict[str, Any] = {
        name: int(await session.scalar(text(sql)) or 0) for name, sql in SUMMARY_QUERIES.items()
    }
    for name, sql in BREAKDOWN_QUERIES.items():
        summary[name] = [list(row) for row in (await session.execute(text(sql))).all()]
    summary["sources"] = [
        dict(row._mapping)
        for row in await session.execute(
            text("SELECT key, license, usage_restriction FROM data_sources ORDER BY key")
        )
    ]
    summary["latest_jobs"] = [
        {**dict(row._mapping), "finished_at": str(row.finished_at)}
        for row in await session.execute(
            text(
                """SELECT DISTINCT ON (j.stage) j.stage, s.key AS source, j.status, j.stats, j.finished_at
                   FROM ingestion_jobs j JOIN data_sources s ON s.id = j.source_id
                   ORDER BY j.stage, j.started_at DESC"""
            )
        )
    ]
    return summary


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def render_markdown(
    summary: dict[str, Any], results: list[CheckResult], generated_at: datetime
) -> str:
    tracks = summary["tracks"]
    lines = [
        "# Catalogue data quality report",
        "",
        f"Generated {generated_at:%Y-%m-%d %H:%M} UTC by `python -m soniqueo_ml catalogue quality`.",
        "",
        "## Catalogue",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Tracks | {tracks:,} |",
        f"| Artists | {summary['artists']:,} |",
        f"| Albums | {summary['albums']:,} |",
        f"| Genres | {summary['genres']:,} |",
        f"| Tracks with ISRC | {summary['tracks_with_isrc']:,} ({_pct(summary['tracks_with_isrc'], tracks)}) |",
        f"| Tracks with duration | {summary['tracks_with_duration']:,} "
        f"({_pct(summary['tracks_with_duration'], tracks)}) |",
        f"| Tracks with track/album genres | {summary['tracks_with_track_or_album_genres']:,} "
        f"({_pct(summary['tracks_with_track_or_album_genres'], tracks)}) |",
        f"| Tracks with any genre (incl. artist) | {summary['tracks_with_any_genre']:,} "
        f"({_pct(summary['tracks_with_any_genre'], tracks)}) |",
        f"| Tracks with audio features | {summary['tracks_with_audio_features']:,} "
        f"({_pct(summary['tracks_with_audio_features'], tracks)}) |",
        f"| Tracks identified by more than one source | {summary['tracks_in_multiple_sources']:,} |",
        f"| Possible duplicates pending review | {summary['pending_match_reviews']:,} |",
        "",
        "### Tracks by source",
        "",
        "| Source | Tracks |",
        "| --- | --- |",
        *[f"| {key} | {count:,} |" for key, count in summary["tracks_by_source"]],
        "",
        "### Identifiers",
        "",
        "| Provider | Match method | Count |",
        "| --- | --- | --- |",
        *[f"| {p} | {m} | {c:,} |" for p, m, c in summary["identifiers_by_provider"]],
        "",
        "### Audio features",
        "",
        "| Source | Version | Tracks |",
        "| --- | --- | --- |",
        *[f"| {s} | {v} | {c:,} |" for s, v, c in summary["features_by_source"]],
        "",
        "### Most common genres (track or album level)",
        "",
        ", ".join(f"{name} ({count:,})" for name, count in summary["top_genres"]) or "none",
        "",
        "## Sources and licences",
        "",
        "| Source | Licence | Usage restriction |",
        "| --- | --- | --- |",
        *[f"| {s['key']} | {s['license']} | {s['usage_restriction']} |" for s in summary["sources"]],
        "",
        "## Latest pipeline runs",
        "",
        "| Stage | Source | Status | Statistics |",
        "| --- | --- | --- | --- |",
        *[
            f"| {j['stage']} | {j['source']} | {j['status']} | `{json.dumps(j['stats'], sort_keys=True)}` |"
            for j in summary["latest_jobs"]
        ],
        "",
        "## Checks",
        "",
        "| Result | Severity | Category | Check | Count |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in results:
        status = "pass" if result.passed else ("**FAIL**" if result.blocking else "flag")
        lines.append(
            f"| {status} | {result.check.severity} | {result.check.category} | "
            f"`{result.check.name}`: {result.check.description} | {result.count:,} |"
        )
    flagged = [r for r in results if not r.passed and r.check.severity is not Severity.INFO]
    if flagged:
        lines += ["", "### Samples", ""]
        for result in flagged:
            lines += [f"**{result.check.name}**", "", "```json"]
            lines += [json.dumps(sample, ensure_ascii=False) for sample in result.samples]
            lines += ["```", ""]
    return "\n".join(lines).rstrip() + "\n"


def write_report(
    summary: dict[str, Any], results: list[CheckResult], markdown_path: Path, history_dir: Path
) -> Path:
    generated_at = datetime.now(UTC)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_markdown(summary, results, generated_at), encoding="utf-8")
    history_dir.mkdir(parents=True, exist_ok=True)
    history = history_dir / f"data-quality-{generated_at:%Y%m%dT%H%M%S}.json"
    history.write_text(
        json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "summary": summary,
                "checks": [
                    {
                        "name": r.check.name,
                        "severity": r.check.severity,
                        "count": r.count,
                        "samples": r.samples,
                    }
                    for r in results
                ],
            },
            default=str,
            indent=1,
        ),
        encoding="utf-8",
    )
    return markdown_path
