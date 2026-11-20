"""The offline context experiment uses the same daypart model as the API."""

import numpy as np
import scipy.sparse as sp

from app.domains.recommendations.context import (
    ContextProfile,
    build_context_profile,
    context_fit,
    daypart,
    daypart_distribution,
)
from soniqueo_ml.evaluation.context_experiment import (
    Listens,
    cross_entropy,
    dayparts_of,
    infer_offsets,
)


def test_offsets_come_from_the_quiet_night_hours() -> None:
    # Silent 20:00-23:59 UTC: that is local 02:00-05:59 at UTC+6.
    hours = np.array([h for h in range(24) if h not in (20, 21, 22, 23)] * 10, dtype=np.int64)
    users = np.zeros(len(hours), dtype=np.int64)
    offsets, confident = infer_offsets(users, hours, 1)
    assert confident[0]
    assert offsets[0] == 6  # local 02:00-05:59 = 20:00-23:59 UTC
    # Too few listens: not trusted.
    _, confident = infer_offsets(users[:50], hours[:50], 1)
    assert not confident[0]


def test_dayparts_match_the_api() -> None:
    hours = np.arange(24, dtype=np.int64)
    names = ("night", "morning", "afternoon", "evening")
    assert [names[i] for i in dayparts_of(hours)] == [daypart(int(h)) for h in hours]


def test_daypart_model_matches_the_api_distribution() -> None:
    # One user, two genres; evening listens lean to genre 1.
    genres = sp.csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0]]))
    items = np.array([0, 0, 0, 1, 1, 1, 1, 1, 0, 1], dtype=np.int64)
    hours = np.array([9, 10, 11, 19, 20, 21, 22, 23, 20, 9], dtype=np.int64)
    train = Listens(
        user=np.zeros(len(items), dtype=np.int64),
        item=items,
        hour=hours,
        at=np.zeros(len(items), dtype="datetime64[s]"),
    )
    test = Listens(
        user=np.array([0], dtype=np.int64),
        item=np.array([1], dtype=np.int64),
        hour=np.array([21], dtype=np.int64),
        at=np.zeros(1, dtype="datetime64[s]"),
    )
    k = 20.0
    loss = cross_entropy(
        train, test, dayparts_of(hours), dayparts_of(test.hour), genres, 1, shrinkage=k
    )

    # The same quantity through the API's functions, with the experiment's overall prior.
    profile = build_context_profile(
        (daypart(int(h)), {"g0": 1.0} if i == 0 else {"g1": 1.0})
        for i, h in zip(items, hours, strict=True)
    )
    population = {"g0": 4 / 10, "g1": 6 / 10}
    overall = {
        g: (profile.overall[g] * len(items) + 5.0 * population[g]) / (len(items) + 5.0)
        for g in ("g0", "g1")
    }
    prior = ContextProfile(overall=overall, dayparts=profile.dayparts, counts=profile.counts)
    expected = -np.log(daypart_distribution(prior, "evening", k)["g1"] + 1e-4)
    assert np.isclose(loss[0], expected)


def test_context_fit_needs_evidence_and_is_bounded() -> None:
    listens = [("evening", {"rock": 1.0})] * 30 + [("morning", {"jazz": 1.0})] * 30
    profile = build_context_profile(listens)
    assert context_fit(profile, "evening", {"rock": 1.0}) > 0
    assert context_fit(profile, "evening", {"jazz": 1.0}) < 0
    assert context_fit(profile, "night", {"rock": 1.0}) == 0.0  # no night evidence
    assert -1.0 <= context_fit(profile, "morning", {"rock": 1.0}) <= 1.0


def test_window_sums_add_up_the_listens_in_each_window() -> None:
    from soniqueo_ml.evaluation.context_experiment import window_sums

    genres = sp.csr_matrix(np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]))
    items = np.array([0, 1, 2, 0], dtype=np.int64)
    sums, lengths = window_sums(
        np.array([0, 1, 3], dtype=np.int64), np.array([2, 4, 3], dtype=np.int64), items, genres
    )
    assert lengths.tolist() == [2, 3, 0]
    assert sums.toarray().tolist() == [[1.0, 1.0], [1.5, 1.5], [0.0, 0.0]]
