"""Pipeline -> database -> API for Milestone 3: publish the collaborative and hybrid models, then
serve a SONIQUEO user and check the online collaborative scores against the offline model."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.auth.schemas import RegisterIn
from app.domains.auth.service import AuthService
from app.domains.recommendations.models import (
    CF_DIMENSIONS,
    ModelArtifact,
    ModelVersion,
    TrackCollaborativeFactors,
    TrackNeighbour,
)
from app.domains.recommendations.personalized import ARTIFACTS, PersonalizedRecommendationService
from app.domains.users.models import User
from app.domains.users.schemas import InteractionBatch, InteractionIn
from app.domains.users.service import UserService
from soniqueo_ml.recommendation.catalogue_data import load_catalogue
from soniqueo_ml.recommendation.collaborative import (
    ALSConfig,
    ItemItemConfig,
    train_als,
    train_item_item,
)
from soniqueo_ml.recommendation.lineage import lineage
from soniqueo_ml.recommendation.popularity import compute_popularity
from soniqueo_ml.recommendation.publish import (
    VersionSpec,
    publish_collaborative,
    publish_content,
    publish_hybrid,
    publish_popularity,
)
from tests.integration.test_recommendation_publish import catalogue_ids, spec, vectors
from tests.recommendation_fixtures import T0, listens

pytestmark = pytest.mark.integration

__all__ = ["catalogue_ids"]

WEIGHTED = {
    "kind": "weighted",
    "weights": {"collaborative_mf": 1.0, "collaborative_item": 1.0, "history": 0.5},
    "calibration": {
        "collaborative_mf": {"a": 1.0, "b": 0.0},
        "collaborative_item": {"a": 1.0, "b": 0.0},
        "history": {"a": 1.0, "b": 0.0},
    },
}


def cf_matrix(n_items: int) -> sp.csr_matrix:
    """Users who play the first three tracks together, and users of the last three."""
    rng = np.random.default_rng(3)
    dense = np.zeros((40, n_items))
    dense[:20, :3] = rng.integers(1, 4, size=(20, 3))
    dense[20:, 3:] = rng.integers(1, 4, size=(20, 3))
    dense[rng.random(dense.shape) < 0.3] = 0
    return sp.csr_matrix(dense)


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


async def publish_all(session: AsyncSession, catalogue_ids: list[str]) -> dict[str, Any]:
    track_ids = np.array(catalogue_ids, dtype=object)
    served = await load_catalogue(session)
    data = listens([("u1", catalogue_ids[0], 1), ("u2", catalogue_ids[3], 2)])
    popularity = compute_popularity(data, track_ids, T0 + pd.Timedelta(days=3))
    await publish_popularity(session, spec("popularity", 1), popularity)
    artist_ids = np.asarray(pd.unique(served.tracks["artist_id"]), dtype=object)
    await publish_content(
        session,
        spec("content", 1),
        track_ids,
        vectors(len(catalogue_ids)),
        artist_ids,
        vectors(len(artist_ids), seed=1),
        np.array([2, 2, 2], dtype=np.int64),
    )
    matrix = cf_matrix(len(catalogue_ids))
    als = train_als(matrix, ALSConfig(factors=CF_DIMENSIONS, iterations=5))
    item_item = train_item_item(matrix, ItemItemConfig(neighbours=3))
    listened = np.bincount(matrix.indices, minlength=len(catalogue_ids)) > 0
    trained_at = datetime(2026, 11, 16, tzinfo=UTC)
    cf_spec = VersionSpec(
        "collaborative",
        {"fold_in": als.fold_in_parameters.params()},
        {"lineage": lineage("collaborative")},
        {},
        trained_at,
    )
    cf = await publish_collaborative(
        session,
        cf_spec,
        track_ids,
        als.item_factors,
        als.idf,
        listened,
        als.gram,
        item_item.similarity,
    )
    hybrid = await publish_hybrid(
        session,
        VersionSpec(
            "hybrid",
            {"ranker": "weighted", "weighted": WEIGHTED, "candidates": {"source_limit": 10}},
            {"lineage": lineage("hybrid")},
            {},
            trained_at,
        ),
        {"ranker_cc0": json.dumps({"feature_names": [], "trees": []}).encode()},
    )
    return {"als": als, "item_item": item_item, "cf": cf, "hybrid": hybrid}


async def test_collaborative_and_hybrid_versions_are_published(
    session: AsyncSession, catalogue_ids: list[str]
) -> None:
    published = await publish_all(session, catalogue_ids)
    cf = published["cf"]
    assert isinstance(cf, dict)
    assert cf["track_factors"] == await session.scalar(
        select(func.count()).select_from(TrackCollaborativeFactors)
    )
    assert cf["neighbour_rows"] == await session.scalar(
        select(func.count()).select_from(TrackNeighbour)
    )
    assert cf["neighbour_rows"] > 0
    artifacts = (await session.scalars(select(ModelArtifact.name))).all()
    assert sorted(artifacts) == ["gram", "ranker_cc0"]
    active = {
        v.model_type: v
        for v in (
            await session.scalars(select(ModelVersion).where(ModelVersion.status == "active"))
        )
    }
    assert set(active) == {"popularity", "content", "collaborative", "hybrid"}
    assert active["hybrid"].training_data["lineage"]["usage_restriction"] == "non_commercial"
    assert active["collaborative"].training_data["lineage"]["commercial_use"] is True


async def test_served_collaborative_scores_match_the_offline_model(
    session: AsyncSession, catalogue_ids: list[str]
) -> None:
    ARTIFACTS.items.clear()
    published = await publish_all(session, catalogue_ids)
    als = published["als"]
    users = UserService(session)
    user = await demo_user(session)
    heard = {0: 3, 1: 2}  # item -> plays: a listener of the first group
    await users.record_events(
        user.id,
        InteractionBatch(
            events=[
                InteractionIn(track_id=uuid.UUID(catalogue_ids[item]), event_type="play")
                for item, count in heard.items()
                for _ in range(count)
            ]
        ),
    )
    response = await PersonalizedRecommendationService(session).for_you(user.id, limit=4)
    assert response.strategy == "personalized"
    statuses = {s.source: s.status for s in response.candidate_sources}
    assert statuses["collaborative_mf"] == "ok"
    assert statuses["collaborative_item"] == "ok"
    recommended = [str(r.track_id) for r in response.recommendations]
    assert not {catalogue_ids[0], catalogue_ids[1]} & set(recommended)
    # The co-listened third track of the first group leads.
    assert recommended[0] == catalogue_ids[2]

    # Online fold-in (pgvector factors + Gram artifact) == offline ALSModel.user_vector.
    items = np.array(list(heard), dtype=np.int64)
    values = np.array(list(heard.values()), dtype=np.float64)
    offline = als.user_vector(items, values) @ als.item_factors.T.astype(np.float64)
    for item in response.recommendations:
        for source in item.sources:
            if source.source == "collaborative_mf":
                index = catalogue_ids.index(str(item.track_id))
                assert source.retrieval_score == pytest.approx(offline[index], rel=1e-3, abs=1e-3)


async def test_catalogue_reset_refuses_to_orphan_users(
    session: AsyncSession, catalogue_ids: list[str]
) -> None:
    from soniqueo_ml.pipelines.catalogue import stage_reset

    await demo_user(session)
    with pytest.raises(RuntimeError, match="SONIQUEO users exist"):
        await stage_reset()
