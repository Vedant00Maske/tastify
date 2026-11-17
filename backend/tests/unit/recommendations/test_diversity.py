import numpy as np
import pytest

from app.domains.recommendations.diversity import POLICIES, DiversityPolicy, compose

RANKED = DiversityPolicy("ranked", mmr_lambda=1.0, max_per_artist=2)


def test_relevance_only_with_artist_cap_and_one_version_per_song() -> None:
    picked = compose(
        np.array([0.9, 0.8, 0.7, 0.6, 0.5]),
        limit=4,
        policy=RANKED,
        artists=["a", "a", "a", "b", "c"],
        song_keys=["s1", "s2", "s3", "s1", "s5"],
    )
    # Third "a" track hits the cap; "b"'s track is another version of song s1.
    assert picked == [0, 1, 4]


def test_no_cap_policy_keeps_every_track_of_an_artist() -> None:
    policy = DiversityPolicy("radio", mmr_lambda=1.0, max_per_artist=None)
    assert compose(np.array([3.0, 2.0, 1.0]), limit=3, policy=policy, artists=["a"] * 3) == [
        0,
        1,
        2,
    ]


def test_mmr_trades_relevance_for_diversity() -> None:
    embeddings = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    relevance = np.array([1.0, 0.95, 0.7])
    artists = ["a", "b", "c"]
    plain = compose(relevance, limit=2, policy=RANKED, artists=artists, embeddings=embeddings)
    diverse = compose(
        relevance,
        limit=2,
        policy=DiversityPolicy("mmr", mmr_lambda=0.5),
        artists=artists,
        embeddings=embeddings,
    )
    assert plain == [0, 1]
    assert diverse == [0, 2]


@pytest.mark.parametrize(("target", "expected"), [(0.2, 2), (0.5, 5), (0.8, 8)])
def test_discovery_target_sets_the_familiar_new_balance(target: float, expected: int) -> None:
    n = 40
    discovery = np.arange(n) % 2 == 1
    picked = compose(
        np.linspace(1.0, 0.0, n),
        limit=10,
        policy=POLICIES["for_you"],
        artists=[f"artist{i}" for i in range(n)],
        discovery=discovery,
        discovery_target=target,
    )
    assert len(picked) == 10
    assert int(discovery[picked].sum()) == expected


def test_discovery_falls_back_when_one_group_runs_out() -> None:
    discovery = np.array([False, False, False, True])
    picked = compose(
        np.array([0.9, 0.8, 0.7, 0.1]),
        limit=4,
        policy=POLICIES["for_you"],
        artists=["a", "b", "c", "d"],
        discovery=discovery,
        discovery_target=0.8,
    )
    assert sorted(picked) == [0, 1, 2, 3]


def test_artist_radio_reserves_a_share_for_the_seed_artist() -> None:
    n = 30
    artists = ["seed"] * 15 + [f"other{i // 3}" for i in range(15)]
    picked = compose(
        np.linspace(1.0, 0.0, n),
        limit=10,
        policy=POLICIES["artist_radio"],
        artists=artists,
        seed_artist="seed",
    )
    chosen = [artists[i] for i in picked]
    assert chosen.count("seed") == 4  # ceil(0.4 * 10)
    assert max(chosen.count(a) for a in set(chosen) - {"seed"}) <= 2


def test_soft_caps_are_relaxed_rather_than_cutting_the_list_short() -> None:
    policy = DiversityPolicy("genre", mmr_lambda=1.0, max_per_artist=None, max_genre_share=0.5)
    picked = compose(
        np.array([0.9, 0.8, 0.7, 0.6]),
        limit=4,
        policy=policy,
        artists=["a", "b", "c", "d"],
        primary_genres=["rock", "rock", "rock", "jazz"],
    )
    assert picked == [0, 1, 3, 2]
    head_policy = DiversityPolicy("head", mmr_lambda=1.0, max_per_artist=None, max_head_share=0.5)
    head = compose(
        np.array([0.9, 0.8, 0.7, 0.6]),
        limit=2,
        policy=head_policy,
        artists=["a", "b", "c", "d"],
        head=np.array([True, True, False, False]),
    )
    assert head == [0, 2]


def test_compose_is_deterministic_and_handles_edge_cases() -> None:
    relevance = np.array([0.5, 0.5, 0.5])
    assert compose(relevance, limit=3, policy=RANKED, artists=["a", "b", "c"]) == [0, 1, 2]
    assert compose(np.array([]), limit=3, policy=RANKED, artists=[]) == []
    assert compose(relevance, limit=0, policy=RANKED, artists=["a", "b", "c"]) == []
    with pytest.raises(ValueError, match="mmr_lambda"):
        DiversityPolicy("bad", mmr_lambda=1.5)


def test_policies_are_category_specific() -> None:
    assert POLICIES["artist_radio"].seed_artist_share is not None
    assert POLICIES["discovery"].max_per_artist == 1
    assert POLICIES["for_you"].discovery
    assert not POLICIES["artist_radio"].discovery
    overridden = POLICIES["for_you"].with_overrides(max_per_artist=3, mmr_lambda=None)
    assert overridden.max_per_artist == 3
    assert overridden.mmr_lambda == POLICIES["for_you"].mmr_lambda
