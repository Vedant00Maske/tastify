"""docs/reports/hybrid-benchmark.md: the Milestone 3 benchmark report (ADR-016).

Everything comes from the pipeline outputs (models/hybrid/*.json) and from live calls to the API
services. The live examples run inside a transaction that is rolled back: the demo user and its
events never persist.
"""

import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.domains.auth.schemas import RegisterIn
from app.domains.auth.service import AuthService
from app.domains.catalogue.models import Artist, Track
from app.domains.recommendations.models import TrackPopularity
from app.domains.recommendations.personalized import PersonalizedRecommendationService
from app.domains.recommendations.repository import RecommendationRepository
from app.domains.users.models import User
from app.domains.users.profile import ExplorationMode
from app.domains.users.schemas import InteractionBatch, InteractionIn, PreferencesIn
from app.domains.users.service import UserService
from soniqueo_ml.evaluation.report import _f, _table

PERSONA = {
    # artist: (tracks, plays per track, days ago of the plays)
    "Radiohead": (4, 4, (6, 13)),
    "Arctic Monkeys": (3, 3, (4, 12)),
    "The Neighbourhood": (3, 3, (3, 10)),
    "Cigarettes After Sex": (3, 3, (0, 2)),
}
SKIPPED = ("Taylor Swift", "Sabrina Carpenter", "Dua Lipa", "Ed Sheeran")

ACCURACY = ("ndcg@10", "precision@10", "recall@10", "map@10", "hit_rate@10")
BEYOND = ("coverage@10", "diversity@10", "artist_diversity@10", "novelty@10")


# --- live examples ---------------------------------------------------------------------------


async def demo_user(session: AsyncSession) -> User:
    """A throwaway account (callers roll the transaction back)."""
    user, _ = await AuthService(session).register(
        RegisterIn(
            email=f"demo-{uuid.uuid4().hex[:12]}@example.invalid",
            password=f"demo-{uuid.uuid4().hex}",
            accept_terms=True,
        ),
        "soniqueo-ml",
    )
    return user


async def _top_tracks(session: AsyncSession, artist: str, count: int) -> list[uuid.UUID]:
    popularity = await RecommendationRepository(session).active_version("popularity")
    statement = (
        select(Track.id)
        .join(Artist, Artist.id == Track.artist_id)
        .where(func.lower(Artist.name) == artist.lower())
    )
    if popularity is not None:
        statement = statement.outerjoin(
            TrackPopularity,
            (TrackPopularity.track_id == Track.id)
            & (TrackPopularity.model_version_id == popularity.id),
        ).order_by(func.coalesce(TrackPopularity.listeners, 0).desc(), Track.id)
    return list((await session.scalars(statement.limit(count))).all())


def _items(response: Any) -> list[dict[str, Any]]:
    return [
        {
            "title": r.title,
            "artist": r.artist,
            "reason": r.reason,
            "discovery": getattr(r, "discovery", None),
            "sources": [s.source for s in getattr(r, "sources", [])],
        }
        for r in response.recommendations
    ]


async def _persona(session: AsyncSession) -> dict[str, Any]:
    users = UserService(session)
    user = await demo_user(session)
    now = datetime.now(UTC)
    events: list[InteractionIn] = []
    for artist, (count, plays, (recent, oldest)) in PERSONA.items():
        tracks = await _top_tracks(session, artist, count)
        for index, track in enumerate(tracks):
            for play in range(plays):
                days = recent + (oldest - recent) * (play + index) / max(plays + count - 2, 1)
                events.append(
                    InteractionIn(
                        track_id=track,
                        event_type="play",
                        occurred_at=now - timedelta(days=days, minutes=index),
                    )
                )
            if artist == "Radiohead" and index < 2:
                events.append(InteractionIn(track_id=track, event_type="like"))
    for artist in SKIPPED:
        for track in await _top_tracks(session, artist, 2):
            for repeat in range(2):
                events.append(
                    InteractionIn(
                        track_id=track,
                        event_type="skip",
                        position_ms=6_000,
                        occurred_at=now - timedelta(days=1 + repeat),
                    )
                )
    recorded = await users.record_events(user.id, InteractionBatch(events=events))
    profile = recorded.profile
    service = PersonalizedRecommendationService(session)
    lists = {}
    for mode in (None, *ExplorationMode):
        await service.for_you(user.id, 10, mode)  # warm caches
        started = time.perf_counter()
        response = await service.for_you(user.id, 10, mode)
        lists[mode.value if mode else f"default ({response.composition.exploration_mode})"] = {
            "ms": round(1000 * (time.perf_counter() - started)),
            "composition": response.composition.model_dump(),
            "items": _items(response),
            "sources": {s.source: s.status for s in response.candidate_sources},
            "ranker": response.ranker,
            "model_versions": response.model_versions,
        }
    return {
        "events": len(events),
        "profile": {
            "genres": [(g.genre, g.score) for g in profile.genre_affinity[:6]],
            "artists": [(a.name, a.score) for a in profile.artist_affinity[:6]],
            "negative": [(a.name, a.score) for a in profile.negative_artists],
            "exploration_preference": profile.exploration_preference,
            "discovery_target": profile.discovery_target,
        },
        "lists": lists,
    }


async def _cold_start(session: AsyncSession) -> dict[str, Any]:
    users = UserService(session)
    service = PersonalizedRecommendationService(session)
    newcomer = await demo_user(session)
    plain = await service.for_you(newcomer.id, 8)
    declared = await demo_user(session)
    artist = await session.scalar(
        select(Artist.id).where(func.lower(Artist.name) == "cigarettes after sex")
    )
    await users.update_preferences(
        declared.id,
        PreferencesIn(preferred_artists=[artist] if artist else [], preferred_genres=["dream pop"]),
    )
    with_taste = await service.for_you(declared.id, 8)
    return {
        "nothing": {"strategy": plain.strategy, "items": _items(plain)},
        "declared": {
            "declared": "Cigarettes After Sex; dream pop",
            "strategy": with_taste.strategy,
            "items": _items(with_taste),
        },
    }


async def _radio(session: AsyncSession) -> dict[str, Any] | None:
    artist = await session.scalar(select(Artist.id).where(func.lower(Artist.name) == "radiohead"))
    if artist is None:
        return None
    service = PersonalizedRecommendationService(session)
    await service.artist_radio(artist, 12)
    started = time.perf_counter()
    response = await service.artist_radio(artist, 12)
    return {"ms": round(1000 * (time.perf_counter() - started)), "items": _items(response)}


async def collect_hybrid_examples() -> dict[str, Any]:
    """Live calls through the API services, in a transaction that is rolled back."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            if await RecommendationRepository(session).active_version("hybrid") is None:
                return {}
            return {
                "persona": await _persona(session),
                "cold_start": await _cold_start(session),
                "artist_radio": await _radio(session),
            }
        finally:
            await session.close()
            await transaction.rollback()


# --- formatting --------------------------------------------------------------------------------


def _rows(results: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> list[list[str]]:
    return [[r["name"], *(_f(r["metrics"].get(k)) for k in keys)] for r in results]


def _find(results: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    return next(r for r in results if r["name"] == name)


def _ci(row: Mapping[str, Any], key: str = "ndcg@10") -> str:
    return f"{row['metrics'][key]:.4f} ± {row['ci95'].get(key, 0.0):.4f}"


def _summary(evaluation: Mapping[str, Any]) -> list[str]:
    test = evaluation["test"]
    results = test["results"]
    served = test["served_variant"]
    profile = _find(results, "content-profile (M2)")
    popularity = _find(results, "popularity")
    best_cf = _find(results, test["best_cf"])
    ltr = _find(results, "hybrid-lambdarank")
    final = _find(results, served)
    paired = test["paired"]
    gain = paired["hybrid-lambdarank vs content-profile (M2)"]
    uncapped = _find(results, "hybrid-lambdarank (no artist cap)")
    modes = {m: _find(results, f"hybrid+mmr [{m}]") for m in ("familiar", "balanced", "explorer")}
    discovery = test["discovery"]
    over_cf = paired[f"hybrid-lambdarank vs {test['best_cf']}"]
    lines = [
        "## Summary",
        "",
        f"Test period {test['window']['cutoff'][:10]} to {test['window']['end'][:10]}, "
        f"{test['users']:,} users, each predicted from earlier listening only. Primary metric "
        "(declared before the test run): NDCG@10 against the Milestone 2 listening-profile model, "
        "the previous best.",
        "",
        *_table(
            ("Model", "NDCG@10 (95% CI)", "Recall@10", "Coverage@10", "Diversity@10", "Novelty@10"),
            [
                [
                    r["name"],
                    _ci(r),
                    _f(r["metrics"]["recall@10"]),
                    _f(r["metrics"]["coverage@10"], 3),
                    _f(r["metrics"].get("diversity@10"), 3),
                    _f(r["metrics"].get("novelty@10"), 2),
                ]
                for r in (popularity, profile, best_cf, ltr, final)
            ],
        ),
        f"- **Hybrid ranking (LambdaRank) vs the Milestone 2 best:** NDCG@10 "
        f"{ltr['metrics']['ndcg@10']:.4f} vs {profile['metrics']['ndcg@10']:.4f}, a paired "
        f"difference of {gain['difference']:+.4f} ± {gain['ci95']:.4f} "
        f"({gain['relative']:+.0%}); better for {gain['a_wins']:.0%} of users, worse for "
        f"{gain['b_wins']:.0%}.",
        f"- **Served configuration** (`{served}`: hybrid ranking, MMR and the familiar/discovery "
        f"balance): NDCG@10 {final['metrics']['ndcg@10']:.4f}, coverage "
        f"{final['metrics']['coverage@10']:.3f}, "
        f"diversity {_f(final['metrics'].get('diversity@10'), 3)}.",
        f"- **Collaborative filtering** alone ({test['best_cf']}) reaches NDCG@10 "
        f"{best_cf['metrics']['ndcg@10']:.4f}; the hybrid ranking is "
        f"{over_cf['relative']:+.0%} relative to it (paired difference "
        f"{over_cf['difference']:+.4f} ± {over_cf['ci95']:.4f}).",
        f"- **Trade-offs are explicit.** Without the artist cap the same ranking scores "
        f"{uncapped['metrics']['ndcg@10']:.4f} (users often play several tracks of one artist in "
        "a row); the cap of 2 is a product rule for the personal mix. The exploration modes trade "
        f"accuracy for discovery: familiar {modes['familiar']['metrics']['ndcg@10']:.4f}, balanced "
        f"{modes['balanced']['metrics']['ndcg@10']:.4f}, explorer "
        f"{modes['explorer']['metrics']['ndcg@10']:.4f}, with "
        f"{discovery['hybrid+mmr [familiar]']['discovery_share@10']:.0%}, "
        f"{discovery['hybrid+mmr [balanced]']['discovery_share@10']:.0%} and "
        f"{discovery['hybrid+mmr [explorer]']['discovery_share@10']:.0%} of tracks by new artists.",
        "",
    ]
    return lines


def _protocol(evaluation: Mapping[str, Any]) -> list[str]:
    timeline = evaluation["timeline"]
    validation = evaluation["validation"]
    return [
        "## 1. Protocol",
        "",
        *_table(
            ("Period", "Window (UTC)", "Used for"),
            [
                [
                    "ranker-train",
                    f"{timeline['ranker_train'][0][:10]} to {timeline['ranker_train'][1][:10]}",
                    "Platt calibration; LambdaRank training (labels: what users played next)",
                ],
                [
                    "validation",
                    f"{timeline['validation'][0][:10]} to {timeline['validation'][1][:10]}",
                    "CF configuration, hybrid weights, LambdaRank early stopping, MMR lambda, "
                    "default exploration mode",
                ],
                [
                    "test",
                    f"{timeline['test'][0][:10]} to {timeline['test'][1][:10]}",
                    "reported once; plus three one-day rolling windows",
                ],
            ],
        ),
        "Every period is predicted from interactions before its start: signals, popularity and "
        "the collaborative models are retrained per period, and the content model uses catalogue "
        "metadata only. A user is evaluated when they have at least 5 distinct earlier tracks and "
        "at least one new track in the period; relevant items are those new tracks (already "
        "heard tracks are never recommended). Lists follow the served rules: at most 2 tracks "
        "per artist and one version per song, unless stated.",
        "",
        "Pre-declared rules: the served ranker is the one with the higher validation NDCG@10; "
        "MMR lambda is the most diverse setting within "
        f"{evaluation['config']['max_ndcg_loss']:.0%} "
        "of the validation NDCG@10 at lambda = 1; the default exploration mode is `auto` "
        f"unless `balanced` scores higher. Validation users: {validation['users']:,}.",
        "",
    ]


def _cf(evaluation: Mapping[str, Any]) -> list[str]:
    cf = evaluation["cf_benchmark"]
    rows = sorted(cf["results"], key=lambda r: -r["metrics"]["ndcg@10"])
    selected = cf["selected"]
    return [
        "## 2. Collaborative filtering (validation)",
        "",
        "Implicit feedback: the matrix holds event-weighted, time-decayed listening (not binary). "
        "ALS (implicit-feedback matrix factorization) runs on BM25-weighted confidences; "
        "item-item and user-user are k-nearest-neighbour models; BPR is a pairwise "
        "factorization. User factors for ALS are folded in, exactly as the API computes them for "
        "SONIQUEO users.",
        "",
        *_table(
            ("Model", "Family", "NDCG@10", "Hit rate@10", "Coverage@10"),
            [
                [
                    r["name"],
                    r["family"],
                    _f(r["metrics"]["ndcg@10"]),
                    _f(r["metrics"]["hit_rate@10"], 3),
                    _f(r["metrics"]["coverage@10"], 3),
                ]
                for r in rows
            ],
        ),
        f"Selected: ALS with {selected['als']['factors']} factors, alpha "
        f"{selected['als']['alpha']:g}, regularization {selected['als']['regularization']:g}; "
        f"item-item {selected['item_item']['weighting']} with "
        f"{selected['item_item']['neighbours']} "
        "neighbours. Item-item keeps at most 100 neighbours per track (the served table holds "
        "tracks x neighbours rows); in an earlier run of this experiment 200 neighbours scored "
        "0.0641 against 0.0638 for 50. User-user and BPR are benchmarks only: serving user-user "
        "would require research users' histories in the application database, which the privacy "
        "policy forbids.",
        "",
    ]


def _candidates(evaluation: Mapping[str, Any]) -> list[str]:
    validation = evaluation["candidates"]["validation"]
    return [
        "## 3. Candidate generation (validation)",
        "",
        f"Six independent sources, merged with their attribution kept: on average "
        f"{validation['mean_candidates']:.0f} candidates per user after filtering, containing "
        f"{validation['union']:.1%} of the tracks users went on to play (the ceiling for any "
        "ranker). Marginal recall: what the union loses without that source.",
        "",
        *_table(
            ("Source", "Recall", "Marginal recall", "Candidates per user"),
            [
                [
                    f"`{name}`",
                    f"{s['recall']:.1%}",
                    f"{s['marginal_recall']:.1%}",
                    f"{s['mean_candidates']:.0f}",
                ]
                for name, s in validation["sources"].items()
            ],
        ),
    ]


def _rankers(evaluation: Mapping[str, Any], rankers: Mapping[str, Any] | None) -> list[str]:
    weighted = evaluation["weighted"]
    ltr = evaluation["lambdarank"]
    validation = evaluation["validation"]
    importance = sorted(ltr["importance"].items(), key=lambda kv: -kv[1])[:8]
    rows = {r["name"]: r for r in validation["results"]}
    return [
        "## 4. Hybrid ranking (validation)",
        "",
        "**Weighted baseline:** S(u, t) = sum of w_c x P_c, each component Platt-calibrated on the "
        "ranker-train period (P_c estimates the probability that the user plays the track), "
        "weights by coordinate ascent on validation:",
        "",
        *_table(
            ("Component", "Weight", "Calibration a", "Calibration b"),
            [
                [
                    c,
                    _f(w, 2),
                    _f(weighted["calibration"].get(c, {}).get("a"), 3),
                    _f(weighted["calibration"].get(c, {}).get("b"), 3),
                ]
                for c, w in weighted["weights"].items()
            ],
        ),
        f"**LambdaRank (LightGBM):** {len(ltr['features'])} features, one query per user; "
        f"selected {ltr['selected']['num_leaves']} leaves, {ltr['best_iteration']} trees (early "
        "stopping on validation). Strongest features by gain: "
        + ", ".join(f"`{n}` {v:.0%}" for n, v in importance)
        + ".",
        "",
        *_table(
            ("Ranker", "NDCG@10", "Recall@10", "Coverage@10"),
            [
                [
                    n,
                    _f(r["metrics"]["ndcg@10"]),
                    _f(r["metrics"]["recall@10"]),
                    _f(r["metrics"]["coverage@10"], 3),
                ]
                for n, r in rows.items()
            ],
        ),
        f"Served ranker (pre-declared rule): **{validation['served_ranker']}**, retrained on "
        "ranker-train + validation before the test.",
        "",
    ]


def _diversity(evaluation: Mapping[str, Any]) -> list[str]:
    validation = evaluation["validation"]
    sweep = validation["diversity_sweep"]
    caps = validation.get("artist_cap_sweep", [])
    modes = validation["modes"]
    lines = [
        "## 5. Diversity and exploration (validation)",
        "",
        "MMR(t) = lambda x relevance(t) - (1 - lambda) x max similarity to the tracks already "
        "chosen (content cosine), with the artist cap and one version per song.",
        "",
        *_table(
            (
                "lambda",
                "NDCG@10",
                "Diversity@10",
                "Artist diversity@10",
                "Coverage@10",
                "Novelty@10",
            ),
            [
                [
                    _f(s["lambda"], 2),
                    _f(s["metrics"]["ndcg@10"]),
                    _f(s["metrics"]["diversity@10"], 3),
                    _f(s["metrics"]["artist_diversity@10"], 3),
                    _f(s["metrics"]["coverage@10"], 3),
                    _f(s["metrics"]["novelty@10"], 2),
                ]
                for s in sweep
            ],
        ),
        f"Selected lambda: **{validation['selected_lambda']:g}**.",
        "",
    ]
    if caps:
        lines += [
            "Artist cap (lambda = 1). The cap is a product rule; this is what it costs in accuracy "
            "on this data, where listening often runs through an artist's album:",
            "",
            *_table(
                ("Max tracks per artist", "NDCG@10", "Artist diversity@10"),
                [
                    [
                        "none" if c["max_per_artist"] is None else c["max_per_artist"],
                        _f(c["metrics"]["ndcg@10"]),
                        _f(c["metrics"]["artist_diversity@10"], 3),
                    ]
                    for c in caps
                ],
            ),
        ]
    lines += [
        "Exploration modes (familiar 20%, balanced 50%, explorer 80% of tracks by artists new to "
        "the user; auto = the user's own exploration preference, bounded to 20-80%):",
        "",
        *_table(
            (
                "Mode",
                "NDCG@10",
                "New-artist share@10",
                "New-artist recall@10",
                "Novelty@10",
                "Diversity@10",
            ),
            [
                [
                    m["mode"],
                    _f(m["metrics"]["ndcg@10"]),
                    f"{m['discovery_share@10']:.0%}",
                    f"{m['discovery_recall@10']:.1%}",
                    _f(m["metrics"]["novelty@10"], 2),
                    _f(m["metrics"]["diversity@10"], 3),
                ]
                for m in modes
            ],
        ),
        f"Default mode (users who did not choose one): **{validation['default_mode']}**. "
        f"{modes[0]['new_artist_relevant']:.0%} of the tracks users actually played next were by "
        "artists new to them.",
        "",
    ]
    return lines


def _test(evaluation: Mapping[str, Any]) -> list[str]:
    test = evaluation["test"]
    results = test["results"]
    discovery = test["discovery"]
    return [
        "## 6. Test results",
        "",
        f"{test['users']:,} users, {test['window']['cutoff'][:10]} to "
        f"{test['window']['end'][:10]}. "
        "Accuracy:",
        "",
        *_table(("Model", *ACCURACY), _rows(results, ACCURACY)),
        "Beyond accuracy (diversity: 1 - mean pairwise content similarity; novelty: mean "
        "self-information, bits; new-artist share: tracks by artists the user never played):",
        "",
        *_table(
            ("Model", *BEYOND, "new-artist share@10"),
            [
                [*row, f"{discovery[row[0]]['discovery_share@10']:.0%}"]
                for row in _rows(results, BEYOND)
            ],
        ),
        "Paired differences in NDCG@10 (same users; 95% CI):",
        "",
        *_table(
            ("Comparison", "Difference", "Relative", "A better / B better (users)"),
            [
                [
                    name,
                    f"{p['difference']:+.4f} ± {p['ci95']:.4f}",
                    f"{p['relative']:+.0%}",
                    f"{p['a_wins']:.0%} / {p['b_wins']:.0%}",
                ]
                for name, p in test["paired"].items()
            ],
        ),
        f"Offline hybrid throughput: {test['hybrid_timing']['ms_per_user']:.1f} ms per user "
        "(profile, six sources, merge, filter, features, every list variant).",
        "",
    ]


def _segments(evaluation: Mapping[str, Any]) -> list[str]:
    seg = evaluation["test"]["segments"]
    models = list(seg["history"])
    history_labels = sorted(
        {label for m in models for label in seg["history"][m]},
        key=lambda s: int(s.rstrip("+").split("-")[0]),
    )
    genre_labels = sorted(
        {label for m in models for label in seg["genre"][m]},
        key=lambda g: -seg["genre"][models[0]].get(g, {}).get("users", 0),
    )
    first = models[0]
    return [
        "## 7. Segments (test)",
        "",
        "NDCG@10 by number of distinct tracks in the user's history:",
        "",
        *_table(
            ("Model", *(f"{h} ({seg['history'][first][h]['users']:,})" for h in history_labels)),
            [[m, *(_f(seg["history"][m][h]["ndcg@10"]) for h in history_labels)] for m in models],
        ),
        "NDCG@10 by the user's dominant genre:",
        "",
        *_table(
            ("Model", *(f"{g} ({seg['genre'][first][g]['users']:,})" for g in genre_labels)),
            [[m, *(_f(seg["genre"][m][g]["ndcg@10"]) for g in genre_labels)] for m in models],
        ),
        "Recall@10 of the relevant tracks by popularity (head = top 1% of tracks by listeners, "
        "mid = next 9%, tail = rest), and each stratum's share of what the model recommends:",
        "",
        *_table(
            ("Model", "Head recall", "Mid recall", "Tail recall", "Head / mid / tail share"),
            [
                [
                    m,
                    _f(seg["popularity"][m]["head"]["recall@10"]),
                    _f(seg["popularity"][m]["mid"]["recall@10"]),
                    _f(seg["popularity"][m]["tail"]["recall@10"]),
                    " / ".join(
                        f"{seg['popularity'][m][s]['share_of_recommendations']:.0%}"
                        for s in ("head", "mid", "tail")
                    ),
                ]
                for m in models
            ],
        ),
    ]


def _rolling(evaluation: Mapping[str, Any]) -> list[str]:
    windows = evaluation["rolling"]
    names = [r["name"] for r in windows[0]["results"]]
    return [
        "## 8. Robustness: rolling one-day windows",
        "",
        "Each day of the test period predicted from all earlier days (models retrained per "
        "cutoff; rankers fixed). NDCG@10:",
        "",
        *_table(
            ("Model", *(f"{w['window']['cutoff'][:10]} ({w['users']:,} users)" for w in windows)),
            [
                [n, *(_f(_find(w["results"], n)["metrics"]["ndcg@10"]) for w in windows)]
                for n in names
            ],
        ),
    ]


def _cold(evaluation: Mapping[str, Any]) -> list[str]:
    cold = evaluation["cold_start"]
    onboarding = evaluation["onboarding"]
    return [
        "## 9. Cold start",
        "",
        f"Users with only 1-4 tracks of history ({cold['users']:,} users, test period):",
        "",
        *_table(
            ("Model", "NDCG@10", "Hit rate@10"),
            [
                [r["name"], _f(r["metrics"]["ndcg@10"]), _f(r["metrics"]["hit_rate@10"], 3)]
                for r in cold["results"]
            ],
        ),
        f"Brand-new users: {onboarding['users']:,} test users treated as if they had only "
        f"answered onboarding (their top {onboarding['declared_genres']} genres and top "
        f"{onboarding['declared_artists']} artists from training):",
        "",
        *_table(
            ("Strategy", "NDCG@10", "Hit rate@10"),
            [
                [r["name"], _f(r["metrics"]["ndcg@10"]), _f(r["metrics"]["hit_rate@10"], 3)]
                for r in onboarding["results"]
            ],
        ),
    ]


def _profiles(evaluation: Mapping[str, Any]) -> list[str]:
    s = evaluation["stability"]
    e = s["exploration"]
    return [
        "## 10. Taste profiles",
        "",
        f"Profiles of the same {s['users']:,} users built three days apart "
        f"({s['window']['before'][:10]} and {s['window']['after'][:10]}): recent listening must "
        "not erase long-term taste.",
        "",
        *_table(
            ("Measure", "Value"),
            [
                ["Long-term embedding, cosine before/after", _f(s["long_term_cosine"], 3)],
                ["Short-term embedding, cosine before/after", _f(s["short_term_cosine"], 3)],
                [
                    "Long-term before vs short-term after",
                    _f(s["long_before_vs_short_after_cosine"], 3),
                ],
                ["Top-10 genres, Jaccard before/after", _f(s["top10_genre_jaccard"], 3)],
                ["Top-10 artists, Jaccard before/after", _f(s["top10_artist_jaccard"], 3)],
            ],
        ),
        f"Exploration preference (distinct artists per distinct track, smoothed) averages "
        f"{e['mean_preference']:.2f}; the share of a user's next new tracks that are by new "
        f"artists averages {e['mean_new_artist_share_of_future_tracks']:.2f}. Correlation between "
        f"the two: Pearson {e['pearson']:.2f}, Spearman {e['spearman']:.2f}.",
        "",
    ]


def _licensing(evaluation: Mapping[str, Any]) -> list[str]:
    results = evaluation["test"]["results"]
    full = _find(results, "hybrid-lambdarank")
    cc0 = _find(results, "hybrid-lambdarank-cc0")
    cc0_info = evaluation["cc0"]
    return [
        "## 11. Licensing: a commercially usable variant",
        "",
        "The served hybrid uses content features derived from MusicBrainz genre tags "
        "(CC BY-NC-SA), so it is **non-commercial** (its lineage records this). A variant "
        "restricted to CC0 signals (ListenBrainz listens, MusicBrainz core data and the user's "
        f"own interactions: candidate sources {', '.join(cc0_info['sources'])}; "
        f"{len(cc0_info['features'])} features) was trained the same way and is stored as an "
        "artifact of the hybrid version, not served:",
        "",
        *_table(
            ("Ranker", "NDCG@10", "Coverage@10", "Diversity@10"),
            [
                [
                    r["name"],
                    _ci(r),
                    _f(r["metrics"]["coverage@10"], 3),
                    _f(r["metrics"].get("diversity@10"), 3),
                ]
                for r in (full, cc0)
            ],
        ),
    ]


def _serving(
    published: Mapping[str, Any] | None,
    retrieval: Mapping[str, Any] | None,
    baseline: Mapping[str, Any] | None,
    evaluation: Mapping[str, Any],
) -> list[str]:
    lines = ["## 12. Serving and versioning", ""]
    if published:
        cf, hybrid = published["collaborative"], published["hybrid"]
        lines += [
            f"- `{cf['version']}`: {cf['track_factors']:,} track factors (pgvector, HNSW on inner "
            f"product), {cf['neighbour_rows']:,} item-item neighbour rows, Gram matrix artifact.",
            f"- `{hybrid['version']}`: ranker artifacts "
            + ", ".join(f"`{a['name']}` ({a['bytes']:,} bytes)" for a in hybrid["artifacts"])
            + "; settings, profile configuration and lineage in the registry.",
            "- Milestone 2 versions stay active and unchanged: "
            + ", ".join(
                f"`{v}`" for k, v in published["kept_active"].items() if k != "collaborative"
            )
            + ".",
        ]
    if baseline:
        lines.append(
            f"- The Milestone 2 baseline (artifacts, configurations, report) is snapshotted with "
            f"checksums in `ml/data/models/baselines/m2/` ({len(baseline['files'])} files)."
        )
    lines.append("")
    if retrieval:
        lines += [
            f"Collaborative retrieval: {retrieval['queries']} user vectors against "
            f"{retrieval['vectors']:,} {retrieval['dimensions']}-dimensional track factors, top "
            f"{retrieval['k']} by inner product (tie-aware recall):",
            "",
            *_table(
                ("Method", "Recall@10", "p50 ms", "p95 ms"),
                [
                    [
                        m["method"],
                        _f(m["recall"], 3),
                        _f(m.get("p50_ms"), 2),
                        _f(m.get("p95_ms"), 2),
                    ]
                    for m in retrieval["methods"]
                ],
            ),
        ]
    reproducibility = evaluation["reproducibility"]
    lines += [
        f"Reproducibility: retraining LambdaRank on the same data gave "
        f"{'an identical' if reproducibility['ranker_identical'] else 'a DIFFERENT'} model; "
        f"regenerating candidates for {reproducibility['candidate_users']} users gave "
        f"{'identical' if reproducibility['candidates_identical'] else 'DIFFERENT'} candidates "
        "and features.",
        "",
    ]
    return lines


def _item_rows(items: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [
        [
            str(i + 1),
            f"{item['artist']} - {item['title']}",
            "new"
            if item.get("discovery")
            else ("" if item.get("discovery") is None else "familiar"),
            item["reason"],
        ]
        for i, item in enumerate(items)
    ]


def _examples(examples: Mapping[str, Any]) -> list[str]:
    if not examples:
        return []
    persona = examples["persona"]
    profile = persona["profile"]
    lines = [
        "## 13. Live examples (API services; demo data rolled back)",
        "",
        f"**Persona.** {persona['events']} events: plays of Radiohead, Arctic Monkeys and The "
        "Neighbourhood over the last two weeks, Cigarettes After Sex in the last two days, likes "
        f"on two Radiohead tracks, and early skips of {', '.join(SKIPPED)}.",
        "",
        "Learned profile: genres "
        + ", ".join(f"{g} {s:.2f}" for g, s in profile["genres"])
        + "; artists "
        + ", ".join(f"{a} {s:.2f}" for a, s in profile["artists"])
        + "; negative "
        + (", ".join(f"{a} {s:.2f}" for a, s in profile["negative"]) or "none")
        + f"; exploration preference {profile['exploration_preference']:.2f}.",
        "",
    ]
    for mode, result in persona["lists"].items():
        composition = result["composition"]
        lines += [
            f"*Mode {mode}* ({composition['familiar']} familiar / {composition['discovery']} new; "
            f"{result['ms']} ms):",
            "",
            *_table(("#", "Track", "Artist for the user", "Reason"), _item_rows(result["items"])),
        ]
    cold = examples["cold_start"]
    lines += [
        "**Cold start**, a user with no history and no preferences:",
        "",
        *_table(
            ("#", "Track", "Artist for the user", "Reason"), _item_rows(cold["nothing"]["items"])
        ),
        f"... and one who only declared {cold['declared']['declared']}:",
        "",
        *_table(
            ("#", "Track", "Artist for the user", "Reason"), _item_rows(cold["declared"]["items"])
        ),
    ]
    radio = examples.get("artist_radio")
    if radio:
        lines += [
            f"**Artist radio: Radiohead** ({radio['ms']} ms; the artist may fill 40% of the list, "
            "other artists two tracks each):",
            "",
            *_table(("#", "Track", "Artist for the user", "Reason"), _item_rows(radio["items"])),
        ]
    return lines


def _limitations() -> list[str]:
    return [
        "## 14. Limitations",
        "",
        "- Two weeks of research listening only: no SONIQUEO users yet, and no skips, likes or "
        "saves in the data. Their weights (spec §8.5), the negative-artist rules and the "
        "negative-artist penalty are configured, tested, but not tuned; they need real usage "
        "(Milestone 8).",
        "- The rankers learn to predict the next days' listening of ListenBrainz users, who skew "
        "towards a few genres; the segments show where the models are weaker.",
        "- Offline retrieval is exact; the API uses HNSW indexes (measured above). The API also "
        "bounds per-request work: item-item scoring reads the user's 300 strongest tracks and ALS "
        "fold-in their 1,000 strongest (the evaluation uses all of them).",
        "- The served hybrid is non-commercial because of MusicBrainz genre tags; the CC0 variant "
        "quantifies the cost of dropping them.",
        "- The user endpoints have no authentication until Milestone 4 and are served only in "
        "local and test environments.",
        "",
    ]


def write_hybrid_report(
    path: Path,
    *,
    evaluation: Mapping[str, Any],
    rankers: Mapping[str, Any] | None,
    published: Mapping[str, Any] | None,
    retrieval: Mapping[str, Any] | None,
    baseline: Mapping[str, Any] | None,
    examples: Mapping[str, Any],
) -> None:
    lines = [
        "# SONIQUEO - Hybrid Recommendation Benchmark (Milestone 3)",
        "",
        f"> Generated by `python -m soniqueo_ml personalize report` on "
        f"{datetime.now(UTC):%Y-%m-%d}. Inputs: {evaluation['interactions']:,} listening events, "
        f"{evaluation['catalogue_items']:,} catalogue tracks, content model "
        f"`{evaluation['content_version']}`. Design: ADR-016. Milestone 2 baseline: "
        "[model-benchmark.md](model-benchmark.md).",
        "",
        *_summary(evaluation),
        *_protocol(evaluation),
        *_cf(evaluation),
        *_candidates(evaluation),
        *_rankers(evaluation, rankers),
        *_diversity(evaluation),
        *_test(evaluation),
        *_segments(evaluation),
        *_rolling(evaluation),
        *_cold(evaluation),
        *_profiles(evaluation),
        *_licensing(evaluation),
        *_serving(published, retrieval, baseline, evaluation),
        *_examples(examples),
        *_limitations(),
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
