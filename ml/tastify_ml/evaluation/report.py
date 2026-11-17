"""Renders docs/reports/model-benchmark.md from the evaluation, publish and retrieval results.

Examples are produced by the backend's RecommendationService against the published models, so the
report shows exactly what the API returns.
"""

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalogue.models import Artist, Track
from app.domains.recommendations.models import ArtistEmbedding, TrackEmbedding, TrackPopularity
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.recommendations.schemas import PopularKind, RecommendationResponse
from app.domains.recommendations.service import RecommendationService
from tastify_ml.evaluation.experiment import CONTENT_VARIANTS

PLUS_MINUS = chr(0x00B1)

SIMILAR_SEEDS = (
    ("Radiohead", "Creep"),
    ("Daft Punk", "One More Time"),
    ("Kendrick Lamar", "HUMBLE."),
    ("Billie Eilish", "bad guy"),
    ("Miles Davis", "So What"),
    ("Metallica", "Enter Sandman"),
)
ARTIST_SEEDS = ("Radiohead", "Taylor Swift", "Daft Punk")
GENRE_SEEDS = ("shoegaze", "k-pop", "jazz")
EXAMPLE_SIZE = 5

MODEL_DESCRIPTIONS = {
    "random": "Uniformly random unheard tracks (floor).",
    "popularity": "Most distinct listeners in the training period.",
    "trending": "Reliable rising trends first (recent vs earlier daily listeners), then "
    "popularity.",
    "genre-popularity": "The user's dominant genre, ranked as `/recommendations/genre/{genre}`.",
    "content-seed": "Tracks similar to the user's most played track, ranked as "
    "`/recommendations/similar/{track_id}`.",
    "content-profile": "Tracks similar to the play-weighted mean of the user's history.",
    "content-artist": "Popular tracks of artists similar to the user's most played artist, ranked "
    "as `/recommendations/artist/{artist_id}`.",
}


# --- live examples ---------------------------------------------------------------------------


async def _seed_track(session: AsyncSession, artist: str, title: str) -> Track | None:
    repository = RecommendationRepository(session)
    content = await repository.active_version("content")
    popularity = await repository.active_version("popularity")
    if content is None or popularity is None:
        return None
    return await session.scalar(
        select(Track)
        .join(Artist, Artist.id == Track.artist_id)
        .join(
            TrackEmbedding,
            (TrackEmbedding.track_id == Track.id) & (TrackEmbedding.model_version_id == content.id),
        )
        .join(
            TrackPopularity,
            (TrackPopularity.track_id == Track.id)
            & (TrackPopularity.model_version_id == popularity.id),
        )
        .where(Artist.name == artist, func.lower(Track.title) == title.lower())
        .order_by(TrackPopularity.listeners.desc())
        .limit(1)
    )


async def _seed_artist(session: AsyncSession, name: str) -> Artist | None:
    content = await RecommendationRepository(session).active_version("content")
    if content is None:
        return None
    return await session.scalar(
        select(Artist)
        .join(
            ArtistEmbedding,
            (ArtistEmbedding.artist_id == Artist.id)
            & (ArtistEmbedding.model_version_id == content.id),
        )
        .where(Artist.name == name)
        .order_by(ArtistEmbedding.track_count.desc())
        .limit(1)
    )


async def _timed(
    call: Callable[[], Awaitable[RecommendationResponse]],
) -> tuple[RecommendationResponse, float]:
    """Runs the call twice and times the second (warm cache), so one cold read does not skew it."""
    await call()
    started = time.perf_counter()
    response = await call()
    return response, (time.perf_counter() - started) * 1000


def _example(seed: str, response: RecommendationResponse, ms: float) -> dict[str, Any]:
    return {
        "seed": seed,
        "model_version": response.model_version,
        "ms": round(ms, 1),
        "items": [
            {"title": i.title, "artist": i.artist, "score": i.score, "reason": i.reason}
            for i in response.recommendations
        ],
    }


async def collect_examples(session: AsyncSession) -> dict[str, list[dict[str, Any]]]:
    service = RecommendationService(session)
    examples: dict[str, list[dict[str, Any]]] = {
        "similar": [],
        "artist": [],
        "genre": [],
        "popular": [],
    }
    for artist_name, title in SIMILAR_SEEDS:
        track = await _seed_track(session, artist_name, title)
        if track is not None:
            response, ms = await _timed(partial(service.similar_tracks, track.id, EXAMPLE_SIZE))
            examples["similar"].append(_example(f"{artist_name} - {track.title}", response, ms))
    for name in ARTIST_SEEDS:
        artist = await _seed_artist(session, name)
        if artist is not None:
            response, ms = await _timed(partial(service.similar_artists, artist.id, EXAMPLE_SIZE))
            examples["artist"].append(_example(name, response, ms))
    for genre in GENRE_SEEDS:
        if await RecommendationRepository(session).find_genre(genre) is not None:
            response, ms = await _timed(partial(service.genre, genre, EXAMPLE_SIZE))
            examples["genre"].append(_example(genre, response, ms))
    for kind in PopularKind:
        response, ms = await _timed(partial(service.popular, EXAMPLE_SIZE, kind))
        examples["popular"].append(_example(kind.value, response, ms))
    await session.rollback()
    return examples


# --- rendering -------------------------------------------------------------------------------


def _table(header: Sequence[str], rows: Sequence[Sequence[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return [*lines, ""]


def _f(value: float | None, digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:.{digits}f}"


def _accuracy_rows(results: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    rows = []
    for r in results:
        m, ci = r["metrics"], r["ci95"]
        rows.append(
            [
                f"`{r['name']}`",
                f"{m['ndcg@10']:.4f} {PLUS_MINUS} {ci['ndcg@10']:.4f}",
                _f(m["precision@10"]),
                _f(m["recall@10"]),
                _f(m["map@10"]),
                _f(m["hit_rate@10"], 3),
                _f(m["ndcg@20"]),
                _f(m["recall@20"]),
            ]
        )
    return rows


def _beyond_rows(results: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [
        [
            f"`{r['name']}`",
            _f(r["metrics"]["coverage@10"], 3),
            _f(r["metrics"].get("diversity@10"), 3),
            _f(r["metrics"].get("artist_diversity@10"), 3),
            _f(r["metrics"].get("novelty@10"), 2),
            f"{r['seconds']:.1f}",
        ]
        for r in results
    ]


ACCURACY_HEADER = (
    "Model",
    "NDCG@10 (95% CI)",
    "P@10",
    "R@10",
    "MAP@10",
    "HR@10",
    "NDCG@20",
    "R@20",
)
BEYOND_HEADER = ("Model", "Coverage@10", "Diversity@10", "Artist div.@10", "Novelty@10", "Time (s)")


def _tuning_lines(selection: Mapping[str, Any]) -> list[str]:
    grid = selection["grid"]
    lines = [
        "Best validation NDCG@10 of the seed mode for each feature-weight variant:",
        "",
    ]
    rows = []
    for variant, config in CONTENT_VARIANTS.items():
        points = [g for g in grid if g["mode"] == "seed" and g["variant"] == variant]
        if not points:
            continue
        best = max(points, key=lambda g: g["ndcg@10"])
        marker = " (selected)" if variant == selection["variant"] else ""
        rows.append(
            [
                f"`{variant}`{marker}",
                config.genre_weight,
                config.categorical_weight,
                config.numeric_weight,
                config.genre_prior_votes,
                best["beta"],
                _f(best["ndcg@10"]),
            ]
        )
    lines += _table(
        ("Variant", "Genres", "Categorical", "Numeric", "Tag prior", "Best beta", "NDCG@10"), rows
    )
    betas = sorted({g["beta"] for g in grid})
    beta_rows = []
    for mode in ("seed", "profile", "artist"):
        values = {
            g["beta"]: g["ndcg@10"]
            for g in grid
            if g["mode"] == mode and g["variant"] == selection["variant"]
        }
        beta_rows.append([mode, *(_f(values.get(b)) for b in betas)])
    lines += [
        "Popularity blend on the selected variant (validation NDCG@10; score = (1 - beta) "
        "x similarity + beta x popularity):",
        "",
        *_table(("Mode", *(f"beta={b}" for b in betas)), beta_rows),
    ]
    return lines


def _example_lines(examples: Mapping[str, list[dict[str, Any]]]) -> list[str]:
    titles = {
        "similar": "`GET /recommendations/similar/{track_id}`",
        "artist": "`GET /recommendations/artist/{artist_id}`",
        "genre": "`GET /recommendations/genre/{genre}`",
        "popular": "`GET /recommendations/popular?kind=...`",
    }
    lines: list[str] = []
    for section, title in titles.items():
        entries = examples.get(section, [])
        if not entries:
            continue
        lines += [f"### {title}", ""]
        for entry in entries:
            lines.append(f"**{entry['seed']}** ({entry['ms']:.0f} ms)")
            lines.append("")
            for rank, item in enumerate(entry["items"], start=1):
                lines.append(
                    f"{rank}. {item['artist']} - {item['title']} "
                    f"(score {item['score']:.3f}): {item['reason']}"
                )
            lines.append("")
    return lines


def _retrieval_lines(retrieval: Mapping[str, Any]) -> list[str]:
    hnsw = retrieval["hnsw"]
    rows = [
        [m["method"], _f(m["recall"], 3), _f(m["p50_ms"], 2), _f(m["p95_ms"], 2)]
        for m in retrieval["methods"]
    ]
    return [
        f"{retrieval['queries']} random query tracks against {retrieval['vectors']:,} "
        f"{retrieval['dimensions']}-dimensional embeddings (`{retrieval['model_version']}`), "
        f"top {retrieval['k']} neighbours excluding the query. HNSW index: m={hnsw['m']}, "
        f"ef_construction={hnsw['ef_construction']}, `{hnsw['operator']}`. Only "
        f"{retrieval.get('distinct_vectors', retrieval['vectors']):,} of the vectors are distinct "
        "(tracks with the same artist, genres and decade coincide), so recall is tie-aware: a "
        f"returned neighbour counts when it is at least as similar as the true {retrieval['k']}th. "
        "pgvector latency includes the database round trip from the pipeline (same host); at "
        "this size a sequential scan is cheap, so HNSW pays off as the catalogue grows. The "
        f"query plan {'uses' if retrieval['plan_uses_hnsw_index'] else 'does NOT use'} the HNSW "
        "index.",
        "",
        *_table(("Method", f"Recall@{retrieval['k']}", "p50 (ms)", "p95 (ms)"), rows),
    ]


def _fma_lines(fma: Mapping[str, Any]) -> list[str]:
    k = fma["k"]
    lines = [
        f"{fma['tracks']:,} FMA tracks with a top-level genre ({fma['genres']} genres), "
        f"{fma['numeric_columns']} numeric columns (log duration and Echonest audio features). "
        f"Genre precision@{k} = share of the {k} nearest neighbours with the same top-level genre.",
        "",
    ]
    lines += _table(
        ("Features", f"Genre precision@{k}"),
        [
            ["random neighbours (expected)", _f(fma[f"random_precision@{k}"], 3)],
            ["audio features", _f(fma[f"audio_precision@{k}"], 3)],
            ["audio features + decade/area", _f(fma[f"audio+metadata_precision@{k}"], 3)],
        ],
    )
    rows = [
        [genre, _f(v["share"], 3), _f(v.get("audio"), 3), _f(v.get("audio+metadata"), 3)]
        for genre, v in list(fma["per_genre"].items())[:10]
    ]
    lines += [
        "Ten most common genres:",
        "",
        *_table(("Genre", "Share", "Audio", "Audio + metadata"), rows),
    ]
    return lines


def write_report(
    path: Path,
    *,
    evaluation: Mapping[str, Any],
    published: Mapping[str, Any] | None,
    retrieval: Mapping[str, Any] | None,
    examples: Mapping[str, list[dict[str, Any]]],
) -> Path:
    test, validation, selection = (
        evaluation["test"],
        evaluation["validation"],
        evaluation["selection"],
    )
    config = evaluation["config"]
    fidelity = evaluation["fidelity"]
    feature_dimensions = int(
        sum(fidelity[f"dimensions_{block}"] for block in ("genres", "categorical", "numeric"))
    )
    betas = selection["beta"]
    lines = [
        "# TASTIFY Model Benchmark (Milestone 2)",
        "",
        f"> Generated by `python -m tastify_ml recommend report` on "
        f"{datetime.now(UTC):%Y-%m-%d %H:%M} UTC. Do not edit by hand: re-run the pipeline.",
        "",
        "## Summary",
        "",
    ]
    by_name = {r["name"]: r["metrics"] for r in test["results"]}
    seed, pop = by_name["content-seed"], by_name["popularity"]
    lines += [
        f"- Favourite-track recommendations (`content-seed`, the `/similar` endpoint) reach "
        f"NDCG@10 {seed['ndcg@10']:.4f} on the held-out period, "
        f"{seed['ndcg@10'] / max(pop['ndcg@10'], 1e-9):.1f}x the popularity baseline "
        f"({pop['ndcg@10']:.4f}) and far above random ({by_name['random']['ndcg@10']:.4f}), while "
        f"covering {seed['coverage@10']:.0%} of the catalogue instead of "
        f"{pop['coverage@10']:.1%}.",
        f"- Selected content features: `{selection['variant']}`; popularity blend "
        f"beta = {betas['seed']} (similar), {betas['profile']} (profile), {betas['artist']} "
        "(artist), chosen on the validation period only.",
    ]
    if retrieval:
        hnsw = [m for m in retrieval["methods"] if m.get("ef_search") == 400] or retrieval[
            "methods"
        ][-1:]
        lines.append(
            f"- HNSW retrieval reaches recall@{retrieval['k']} {hnsw[0]['recall']:.3f} at "
            f"ef_search={hnsw[0].get('ef_search')} (p50 {hnsw[0]['p50_ms']:.1f} ms); the API "
            "uses ef_search=400 with a 200-candidate pool."
        )
    if published:
        lines.append(
            f"- Published: `{published['content']['version']}` "
            f"({published['content']['track_embeddings']:,} track and "
            f"{published['content']['artist_embeddings']:,} artist embeddings) and "
            f"`{published['popularity']['version']}` ({published['popularity']['rows']:,} tracks)."
        )
    lines += [
        "",
        "## Data and protocol",
        "",
        f"- Catalogue: {evaluation['catalogue_items']:,} tracks (MusicBrainz-sourced; the "
        "research-only FMA source is excluded from serving and evaluated separately below).",
        f"- Interactions: {evaluation['interactions']:,} de-duplicated ListenBrainz listens by "
        "pseudonymous users (docs/DATA_SOURCES.md).",
        f"- Validation: train `{validation['window']['train_start']}` to "
        f"`{validation['window']['cutoff']}`, predict until `{validation['window']['end']}` "
        f"({validation['users']:,} sampled users). Used only for tuning.",
        f"- Test: train `{test['window']['train_start']}` to `{test['window']['cutoff']}`, predict "
        f"until `{test['window']['end']}` ({test['users']:,} users, all eligible). Used once.",
        f"- Eligible users have at least {config['min_history']} distinct training tracks and at "
        "least one new track in the predicted period. Relevant items are tracks first heard in the "
        f"predicted period (on average {test['mean_relevant']:.1f} per user); already heard tracks "
        "are never recommended.",
        "- No future leakage: histories and popularity come only from interactions before the "
        "cutoff (asserted by `temporal_split`); content embeddings use catalogue metadata only.",
        f"- Trending is only defined where reliable: {test['trending_reliable_tracks']:,} tracks "
        "met the threshold in the test training period.",
        "",
        "Models:",
        "",
        *_table(
            ("Model", "Description"),
            [[f"`{name}`", text] for name, text in MODEL_DESCRIPTIONS.items()],
        ),
        "## Test results",
        "",
        "Accuracy (mean over users; 95% normal-approximation confidence interval for NDCG@10):",
        "",
        *_table(ACCURACY_HEADER, _accuracy_rows(test["results"])),
        "Beyond accuracy (Diversity = 1 - mean pairwise content similarity; Novelty = mean "
        "self-information in bits; Time = generating all lists):",
        "",
        *_table(BEYOND_HEADER, _beyond_rows(test["results"])),
        "### Ablations (seed mode, test period)",
        "",
        *_table(ACCURACY_HEADER, _accuracy_rows(test["ablations"])),
        *_table(BEYOND_HEADER, _beyond_rows(test["ablations"])),
        "## Tuning (validation period)",
        "",
        *_tuning_lines(selection),
        "## Embedding compression",
        "",
        f"Truncated SVD keeps {fidelity['explained_variance']:.1%} of the variance of the "
        f"{feature_dimensions:,}-dimensional feature space "
        f"({int(fidelity['dimensions_genres'])} genres, "
        f"{int(fidelity['dimensions_categorical'])} categorical, "
        f"{int(fidelity['dimensions_numeric'])} numeric). Over {fidelity['queries']:,} random "
        f"tracks, {fidelity['neighbour_recall@10']:.1%} of the 10 nearest neighbours in the full "
        "space are also the 10 nearest in the 128-dimensional embedding.",
        "",
    ]
    if retrieval:
        lines += ["## Retrieval: exact vs approximate", "", *_retrieval_lines(retrieval)]
    if "fma_experiment" in evaluation:
        lines += [
            "## FMA experiment (research-only)",
            "",
            *_fma_lines(evaluation["fma_experiment"]),
        ]
    if any(examples.values()):
        lines += [
            "## Examples from the API",
            "",
            "Produced by the backend `RecommendationService` against the published models "
            "(timings are service-level with a warm cache, including all database queries).",
            "",
            *_example_lines(examples),
        ]
    lines += [
        "## Limitations",
        "",
        "- Two weeks of listens make for short training periods; trending in particular needs "
        "more history to become broadly reliable.",
        "- The catalogue was selected by listener counts over the whole two-week window, so the "
        "candidate set itself carries mild knowledge of the test period (equally for all models).",
        "- Relevance is next-period listening: content similarity is not penalized for "
        "recommending good tracks the user simply did not play in three days.",
        "- Genre tags (CC BY-NC-SA) are the strongest signal, so the served content model inherits "
        "the non-commercial restriction (ADR-013).",
        "- AcousticBrainz audio features exist for about 60% of tracks and stop in 2022.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "cd ml",
        "python -m tastify_ml recommend all   # evaluate, publish, benchmark, report",
        "```",
        "",
        f"Evaluation seed {config['seed']}; all random choices are seeded, so re-running on the "
        f"same data gives the same tables (timings aside). Interactions file SHA-256: "
        f"`{evaluation.get('interactions_sha256', 'n/a')}`.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
