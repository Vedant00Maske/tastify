import numpy as np
import pytest

from app.domains.recommendations.candidate_generation import SOURCE_ORDER
from app.domains.recommendations.features import (
    COMMERCIAL_FEATURES,
    FEATURE_INDEX,
    FEATURE_NAMES,
    FEATURES,
    FeatureInputs,
    feature_matrix,
)
from app.domains.recommendations.hybrid_ranking import (
    Platt,
    Tree,
    TreeEnsembleRanker,
    WeightedHybridRanker,
    demote_negative_artists,
    normalized_relevance,
)


def inputs(n: int = 3, **overrides: object) -> FeatureInputs:
    values: dict[str, object] = {
        "popularity": np.linspace(0.1, 0.3, n),
        "novelty": np.linspace(0.9, 0.7, n),
        "artist_affinity": np.zeros(n),
        "artist_known": np.zeros(n),
        "artist_negative": np.zeros(n),
        "source_ranks": np.full((n, len(SOURCE_ORDER)), np.inf),
        "history_size": 9,
        "exploration": 0.4,
    }
    values.update(overrides)
    return FeatureInputs(**values)  # type: ignore[arg-type]


def test_feature_matrix_columns_and_missing_signals() -> None:
    ranks = np.full((2, len(SOURCE_ORDER)), np.inf)
    ranks[0, 0] = 2
    matrix = feature_matrix(
        inputs(
            2,
            source_ranks=ranks,
            seed_similarity=np.array([[0.2, 0.8], [0.4, 0.4]]),
            cf_mf_score=np.array([np.nan, 1.5]),
        )
    )
    assert matrix.shape == (2, len(FEATURES))
    assert matrix.dtype == np.float32
    assert np.isfinite(matrix).all()
    row = dict(zip(FEATURE_NAMES, matrix[0].tolist(), strict=True))
    assert row["content_seed_max"] == pytest.approx(0.8)
    assert row["content_seed_mean"] == pytest.approx(0.5)
    assert row["cf_mf_score"] == 0.0  # NaN -> 0
    assert row["profile_sim"] == 0.0  # unavailable -> 0
    assert row["user_history_log"] == pytest.approx(np.log1p(9))
    assert row[f"rr_{SOURCE_ORDER[0].value}"] == pytest.approx(0.5)
    assert row[f"rr_{SOURCE_ORDER[1].value}"] == 0.0
    assert feature_matrix(inputs(0)).shape == (0, len(FEATURES))


def test_commercial_features_exclude_content_derived_signals() -> None:
    assert "cf_mf_score" in COMMERCIAL_FEATURES
    assert "popularity" in COMMERCIAL_FEATURES
    assert not {"content_seed_max", "profile_sim", "rr_content_based"} & set(COMMERCIAL_FEATURES)
    assert {f.restriction for f in FEATURES} == {"none", "non_commercial"}


def test_platt_is_a_monotone_probability() -> None:
    values = Platt(2.0, -1.0)(np.array([-10.0, 0.0, 0.5, 10.0]))
    assert values[1] == pytest.approx(1 / (1 + np.e))
    assert values[2] == pytest.approx(0.5)
    assert np.all(np.diff(values) > 0)
    assert values.min() > 0
    assert values.max() < 1


def test_weighted_ranker_combines_calibrated_components() -> None:
    features = np.zeros((2, len(FEATURES)), dtype=np.float32)
    features[0, FEATURE_INDEX["cf_mf_score"]] = 1.0
    features[1, FEATURE_INDEX["popularity"]] = 1.0
    ranker = WeightedHybridRanker(
        {"collaborative_mf": 2.0, "popularity": 1.0, "novelty": 0.0},
        {"collaborative_mf": Platt(1.0, 0.0), "popularity": Platt(1.0, 0.0)},
    )
    scores = ranker.score(features)
    assert scores[0] == pytest.approx(2 * Platt(1, 0)(np.array([1.0]))[0] + 0.5)
    assert scores[0] > scores[1]
    assert WeightedHybridRanker.from_params(ranker.params()).score(features) == pytest.approx(
        scores
    )
    with pytest.raises(ValueError, match="unknown components"):
        WeightedHybridRanker({"magic": 1.0}, {})
    with pytest.raises(ValueError, match="without calibration"):
        WeightedHybridRanker({"history": 1.0}, {})


# A LightGBM-style dump: one split on popularity, one single-leaf tree.
DUMP = {
    "feature_names": ["popularity", "cf_mf_score"],
    "tree_info": [
        {
            "tree_structure": {
                "split_index": 0,
                "split_feature": 0,
                "threshold": 0.5,
                "decision_type": "<=",
                "default_left": True,
                "missing_type": "NaN",
                "left_child": {"leaf_index": 0, "leaf_value": -1.0},
                "right_child": {
                    "split_index": 1,
                    "split_feature": 1,
                    "threshold": 0.0,
                    "decision_type": "<=",
                    "default_left": False,
                    "missing_type": "Zero",
                    "left_child": {"leaf_index": 1, "leaf_value": 0.5},
                    "right_child": {"leaf_index": 2, "leaf_value": 2.0},
                },
            }
        },
        {"tree_structure": {"leaf_value": 0.25}},
    ],
}


def test_tree_ensemble_follows_lightgbm_decisions() -> None:
    ranker = TreeEnsembleRanker.from_lightgbm_dump(DUMP)
    features = np.zeros((5, len(FEATURES)), dtype=np.float32)
    pop, cf = FEATURE_INDEX["popularity"], FEATURE_INDEX["cf_mf_score"]
    features[:, pop] = [0.2, 0.9, 0.9, np.nan, 0.9]
    features[:, cf] = [5.0, -1.0, 3.0, 3.0, 0.0]
    # NaN popularity -> default left; zero cf with missing_type Zero -> default right.
    assert ranker.score(features) == pytest.approx([-0.75, 0.75, 2.25, -0.75, 2.25])
    assert ranker.kind == "lambdarank"
    restored = TreeEnsembleRanker.from_dict(ranker.to_dict())
    assert restored.score(features) == pytest.approx(ranker.score(features))


def test_tree_with_missing_type_none_reads_nan_as_zero() -> None:
    tree = Tree.from_dict(
        {
            "feature": [0],
            "threshold": [-0.5],
            "default_left": [True],
            "missing": [0],
            "left": [-1],
            "right": [-2],
            "leaf_value": [1.0, 2.0],
        }
    )
    assert tree.predict(np.array([[np.nan], [-1.0]])).tolist() == [2.0, 1.0]


def test_unknown_model_features_are_rejected() -> None:
    with pytest.raises(ValueError, match="does not compute"):
        TreeEnsembleRanker((), ("not_a_feature",))


def test_relevance_normalization_and_negative_demotion() -> None:
    assert normalized_relevance(np.array([2.0, 4.0, 3.0])).tolist() == [0.0, 1.0, 0.5]
    assert normalized_relevance(np.array([1.0, 1.0])).tolist() == [1.0, 1.0]
    assert len(normalized_relevance(np.array([]))) == 0
    demoted = demote_negative_artists(np.array([1.0, 1.0]), np.array([0.0, 1.0]), penalty=0.5)
    assert demoted.tolist() == [1.0, 0.5]


def test_percentile_ranks_average_ties_and_ignore_candidate_order() -> None:
    from app.domains.recommendations.features import percentile_ranks

    assert percentile_ranks(np.array([0.2, 0.0, 0.0, 0.9])).tolist() == pytest.approx(
        [2 / 3, 1 / 6, 1 / 6, 1.0]
    )
    assert percentile_ranks(np.array([5.0])).tolist() == [0.0]
    values = np.array([0.3, 0.1, 0.7, 0.1])
    shuffled = np.array([2, 0, 3, 1])
    assert percentile_ranks(values)[shuffled] == pytest.approx(percentile_ranks(values[shuffled]))


def test_rank_features_follow_their_score_features() -> None:
    matrix = feature_matrix(inputs(3, cf_mf_score=np.array([0.5, 2.0, -1.0])))
    assert matrix[:, FEATURE_INDEX["q_rank_cf_mf_score"]].tolist() == pytest.approx([0.5, 1.0, 0.0])
    assert "q_rank_cf_mf_score" in COMMERCIAL_FEATURES
    assert "q_rank_profile_sim" not in COMMERCIAL_FEATURES
