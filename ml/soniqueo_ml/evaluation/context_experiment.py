"""Does time of day predict what a listener plays? (Milestone 6; ADR-019, context-benchmark.md)

The API nudges rankings with a *context fit*: genres a user plays more of in the current
daypart rank a little higher (`app.domains.recommendations.context`). This experiment checks
the premise on the research listens before that nudge is switched on.

Method (chronological, no future data in any profile):
- train: everything before the validation period; validation: two days; test: the last two days
  (profiles for the test are rebuilt from train + validation);
- research timestamps are UTC and listeners live anywhere, so each user's UTC offset is
  inferred from the quietest four hours of their training activity (assumed to be 02:00-05:59
  local); users without a clear quiet period are left out;
- a listen's genres are the track's genre weights (normalized); the *overall* model predicts them
  from the user's overall genre distribution (smoothed toward the population), the *daypart*
  model from the distribution in the listen's daypart, shrunk toward the overall one with `K`
  pseudo-listens (`context.daypart_distribution`). Score: cross-entropy (lower is better);
- controls: the same daypart model on UTC hours (no offset inference) and on dayparts shuffled
  within each user, which keeps the extra smoothing but removes any time-of-day signal.
- `K` is chosen on validation; the test period is used once.
"""

import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
import scipy.sparse as sp

from app.domains.recommendations.context import DAYPARTS, MIN_DAYPART_EVENTS
from soniqueo_ml.evaluation.experiment import data_end, genre_affinity_matrix
from soniqueo_ml.recommendation.catalogue_data import CatalogueData

logger = logging.getLogger(__name__)

SLEEP_HOURS = (2, 3, 4, 5)  # assumed quietest local hours
MIN_TRAIN_LISTENS = 100
MAX_SLEEP_SHARE = 0.05  # a "clear" quiet period: under 5% of a user's listens
POPULATION_PSEUDO = 5.0  # overall profile smoothed toward the population
SHRINKAGE_GRID = (5.0, 10.0, 20.0, 50.0, 100.0)
SESSION_WINDOW_S = 60 * 60  # the listens of the previous hour form the session
DAY_S = 24 * 60 * 60
SESSION_SHRINKAGE_GRID = (1.0, 2.0, 5.0, 10.0, 20.0)
EPS = 1e-4
FloatArray = npt.NDArray[np.float64]


@dataclass
class Listens:
    """Mapped listens: user code, item, UTC hour, timestamp, sorted by time."""

    user: npt.NDArray[np.int64]
    item: npt.NDArray[np.int64]
    hour: npt.NDArray[np.int64]
    at: npt.NDArray[np.datetime64]

    def take(self, mask: npt.NDArray[np.bool_]) -> "Listens":
        return Listens(self.user[mask], self.item[mask], self.hour[mask], self.at[mask])


def infer_offsets(
    users: npt.NDArray[np.int64], hours: npt.NDArray[np.int64], n_users: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.bool_]]:
    """Per user: the UTC offset (hours) whose local 02:00-05:59 holds the fewest listens, and
    whether that quiet period is clear enough to trust."""
    histogram = np.zeros((n_users, 24), dtype=np.float64)
    np.add.at(histogram, (users, hours), 1.0)
    totals = histogram.sum(axis=1)
    offsets = np.arange(-11, 15)
    # Listens in local SLEEP_HOURS for offset o: UTC hours (local - o) mod 24.
    mass = np.stack(
        [histogram[:, [(h - o) % 24 for h in SLEEP_HOURS]].sum(axis=1) for o in offsets], axis=1
    )
    best = mass.argmin(axis=1)
    share = mass[np.arange(n_users), best] / np.maximum(totals, 1.0)
    confident = (totals >= MIN_TRAIN_LISTENS) & (share <= MAX_SLEEP_SHARE)
    return offsets[best].astype(np.int64), confident


def dayparts_of(hours: npt.NDArray[np.int64]) -> npt.NDArray[np.int64]:
    return (hours % 24) // 6  # index into DAYPARTS


def _aggregate(
    groups: npt.NDArray[np.int64], n_groups: int, genres: sp.csr_matrix
) -> sp.csr_matrix:
    """Sum of the listens' normalized genre rows per group."""
    selector = sp.csr_matrix(
        (np.ones(len(groups)), (groups, np.arange(len(groups)))), shape=(n_groups, len(groups))
    )
    return (selector @ genres).tocsr()


def _row_normalize(matrix: sp.csr_matrix) -> sp.csr_matrix:
    sums = np.asarray(matrix.sum(axis=1)).ravel()
    scale = np.divide(1.0, sums, out=np.zeros_like(sums), where=sums > 0)
    return sp.diags(scale) @ matrix


def _lookup(
    matrix: sp.csr_matrix, rows: npt.NDArray[np.int64], cols: npt.NDArray[np.int64]
) -> FloatArray:
    if len(rows) == 0:
        return np.zeros(0)
    return np.asarray(matrix[rows, cols]).ravel().astype(np.float64)


def cross_entropy(
    train: Listens,
    test: Listens,
    parts_train: npt.NDArray[np.int64],
    parts_test: npt.NDArray[np.int64],
    genres: sp.csr_matrix,
    n_users: int,
    shrinkage: float | None,
) -> FloatArray:
    """Per test listen: -sum_g w_g log q(g); q is the overall model (shrinkage None) or the
    daypart model shrunk toward it."""
    train_genres = genres[train.item]
    population = np.asarray(train_genres.sum(axis=0)).ravel()
    population = population / population.sum()
    user_sum = _aggregate(train.user, n_users, train_genres)
    user_n = np.bincount(train.user, minlength=n_users).astype(np.float64)

    test_genres = genres[test.item].tocoo()
    event, genre, weight = test_genres.row, test_genres.col, test_genres.data
    users = test.user[event]
    overall = (_lookup(user_sum, users, genre) + POPULATION_PSEUDO * population[genre]) / (
        user_n[users] + POPULATION_PSEUDO
    )
    q = overall
    if shrinkage is not None:
        groups = n_users * len(DAYPARTS)
        part_sum = _aggregate(train.user * len(DAYPARTS) + parts_train, groups, train_genres)
        part_n = np.bincount(train.user * len(DAYPARTS) + parts_train, minlength=groups).astype(
            np.float64
        )
        keys = users * len(DAYPARTS) + parts_test[event]
        # context.daypart_distribution, with the overall model as the prior.
        q = (_lookup(part_sum, keys, genre) + shrinkage * overall) / (part_n[keys] + shrinkage)
    losses = -weight * np.log(q + EPS)
    return np.bincount(event, weights=losses, minlength=len(test.item)).astype(np.float64)


def overall_probability(
    train: Listens, test: Listens, genres: sp.csr_matrix, n_users: int
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], FloatArray, FloatArray]:
    """(event, genre, weight, q_overall) at every genre of every test listen."""
    train_genres = genres[train.item]
    population = np.asarray(train_genres.sum(axis=0)).ravel()
    population = population / population.sum()
    user_sum = _aggregate(train.user, n_users, train_genres)
    user_n = np.bincount(train.user, minlength=n_users).astype(np.float64)
    coo = genres[test.item].tocoo()
    users = test.user[coo.row]
    overall = (_lookup(user_sum, users, coo.col) + POPULATION_PSEUDO * population[coo.col]) / (
        user_n[users] + POPULATION_PSEUDO
    )
    return (
        coo.row.astype(np.int64),
        coo.col.astype(np.int64),
        coo.data.astype(np.float64),
        overall,
    )


def window_sums(
    starts: npt.NDArray[np.int64],
    ends: npt.NDArray[np.int64],
    items: npt.NDArray[np.int64],
    genres: sp.csr_matrix,
) -> tuple[sp.csr_matrix, npt.NDArray[np.int64]]:
    """Per target: the summed genre rows of items[start:end) and the window length."""
    lengths = np.maximum(ends - starts, 0)
    total = int(lengths.sum())
    rows = np.repeat(np.arange(len(starts)), lengths)
    offsets = np.repeat(np.cumsum(lengths) - lengths, lengths)
    cols = np.repeat(starts, lengths) + (np.arange(total) - offsets)
    selector = sp.csr_matrix(
        (np.ones(total), (rows, items[cols])), shape=(len(starts), genres.shape[0])
    )
    return (selector @ genres).tocsr(), lengths


def _mean_by_user(values: FloatArray, users: npt.NDArray[np.int64]) -> float:
    sums = np.bincount(users, weights=values)
    counts = np.bincount(users)
    present = counts > 0
    return float(np.mean(sums[present] / counts[present]))


def run_context_experiment(
    interactions: pd.DataFrame, catalogue: CatalogueData, seed: int = 7
) -> dict[str, Any]:
    index = catalogue.item_index()
    items = interactions["track_id"].astype(str).map(index)
    frame = interactions.assign(item=items).dropna(subset=["item"]).sort_values("listened_at")
    matrix, _names = genre_affinity_matrix(catalogue)
    genres = _row_normalize(matrix.tocsr())
    has_genre = np.asarray(genres.sum(axis=1)).ravel() > 0
    frame = frame[has_genre[frame["item"].astype(np.int64).to_numpy()]]

    user_codes, user_keys = pd.factorize(frame["user_key"].astype(str))
    stamps = pd.to_datetime(frame["listened_at"], utc=True)
    listens = Listens(
        user=user_codes.astype(np.int64),
        item=frame["item"].to_numpy(dtype=np.int64),
        hour=stamps.dt.hour.to_numpy().astype(np.int64),
        at=stamps.to_numpy(),
    )
    n_users = len(user_keys)
    end = data_end(frame)
    test_start, val_start = end - pd.Timedelta(days=2), end - pd.Timedelta(days=4)
    at = pd.DatetimeIndex(listens.at)
    train_mask = np.asarray(at < val_start)
    val_mask = np.asarray((at >= val_start) & (at < test_start))
    test_mask = np.asarray((at >= test_start) & (at < end))

    offsets, confident = infer_offsets(listens.user[train_mask], listens.hour[train_mask], n_users)
    local_parts = dayparts_of(listens.hour + offsets[listens.user])
    utc_parts = dayparts_of(listens.hour)
    rng = np.random.default_rng(seed)
    shuffled_parts = local_parts.copy()
    # Shuffle dayparts within each user (keeps how often each daypart occurs per user).
    order = np.argsort(listens.user, kind="stable")
    for user_rows in np.split(order, np.flatnonzero(np.diff(listens.user[order])) + 1):
        shuffled_parts[user_rows] = rng.permutation(shuffled_parts[user_rows])

    keep = confident[listens.user]

    def evaluate(fit: npt.NDArray[np.bool_], target: npt.NDArray[np.bool_]) -> dict[str, Any]:
        train, test = listens.take(fit & keep), listens.take(target & keep)
        rows: dict[str, Any] = {"listens": len(test.item), "users": len(np.unique(test.user))}
        base = cross_entropy(
            train, test, utc_parts[fit & keep], utc_parts[target & keep], genres, n_users, None
        )
        rows["overall"] = _mean_by_user(base, test.user)
        for name, parts in (
            ("daypart", local_parts),
            ("utc", utc_parts),
            ("shuffled", shuffled_parts),
        ):
            for k in SHRINKAGE_GRID:
                loss = cross_entropy(
                    train, test, parts[fit & keep], parts[target & keep], genres, n_users, k
                )
                rows[f"{name}@{int(k)}"] = _mean_by_user(loss, test.user)
        return rows

    validation = evaluate(train_mask, val_mask)
    session = evaluate_sessions(listens, genres, n_users, train_mask, val_mask, test_mask)
    best_k = min(SHRINKAGE_GRID, key=lambda k: validation[f"daypart@{int(k)}"])
    test = evaluate(train_mask | val_mask, test_mask)

    def lift(key: str, period: dict[str, Any]) -> float:
        return float((period["overall"] - period[key]) / period["overall"])

    # Evidence per user-daypart at test time, against the serving threshold.
    fit_rows = train_mask | val_mask
    part_counts = np.bincount(
        listens.user[fit_rows & keep] * len(DAYPARTS) + local_parts[fit_rows & keep],
        minlength=n_users * len(DAYPARTS),
    ).reshape(n_users, len(DAYPARTS))
    tested_users = np.unique(listens.user[test_mask & keep])
    usable = (
        float(np.mean(part_counts[tested_users] >= MIN_DAYPART_EVENTS))
        if len(tested_users)
        else 0.0
    )
    return {
        "users_total": int(n_users),
        "users_with_offset": int(confident.sum()),
        "offset_distribution": {
            int(o): int(c)
            for o, c in zip(*np.unique(offsets[confident], return_counts=True), strict=True)
        },
        "window": {
            "validation_start": str(val_start.date()),
            "test_start": str(test_start.date()),
            "end": str(end.date()),
        },
        "best_shrinkage": best_k,
        "validation": validation,
        "test": test,
        "test_lift": {
            "daypart": lift(f"daypart@{int(best_k)}", test),
            "utc": lift(f"utc@{int(best_k)}", test),
            "shuffled": lift(f"shuffled@{int(best_k)}", test),
        },
        "daypart_evidence_share": usable,
        "min_daypart_events": MIN_DAYPART_EVENTS,
        "session": session,
    }


def evaluate_sessions(
    listens: Listens,
    genres: sp.csr_matrix,
    n_users: int,
    train_mask: npt.NDArray[np.bool_],
    val_mask: npt.NDArray[np.bool_],
    test_mask: npt.NDArray[np.bool_],
) -> dict[str, Any]:
    """Session context: the listens of the previous hour, against the overall profile and a
    control (the same hour one day earlier). No time zone needed: windows are relative."""
    seconds = (listens.at.astype("datetime64[s]") - np.datetime64(0, "s")).astype(np.int64)
    order = np.lexsort((seconds, listens.user))
    rank = np.empty(len(order), dtype=np.int64)
    rank[order] = np.arange(len(order))
    base = int(seconds.min())
    span = int(seconds.max()) - base + 2 * DAY_S + SESSION_WINDOW_S + 1
    key = listens.user[order] * span + (seconds[order] - base)
    item_sorted = listens.item[order]
    position = np.arange(len(order))
    session_start = np.searchsorted(key, key - SESSION_WINDOW_S, side="left")
    control_start = np.searchsorted(key, key - DAY_S - SESSION_WINDOW_S, side="left")
    control_end = np.searchsorted(key, key - DAY_S, side="left")

    def run(fit: npt.NDArray[np.bool_], target: npt.NDArray[np.bool_]) -> dict[str, Any]:
        train, test = listens.take(fit), listens.take(target)
        event, genre, weight, overall = overall_probability(train, test, genres, n_users)
        positions = rank[np.flatnonzero(target)]
        windows = {
            "session": window_sums(
                session_start[positions], position[positions], item_sorted, genres
            ),
            "previous_day": window_sums(
                control_start[positions], control_end[positions], item_sorted, genres
            ),
        }
        both = (windows["session"][1] > 0) & (windows["previous_day"][1] > 0)
        evaluated = both[event]
        users = test.user[both]
        rows: dict[str, Any] = {"listens": int(both.sum()), "users": len(np.unique(users))}

        def score(q: FloatArray) -> float:
            losses = np.bincount(
                event[evaluated],
                weights=-weight[evaluated] * np.log(q[evaluated] + EPS),
                minlength=len(test.item),
            ).astype(np.float64)
            return _mean_by_user(losses[both], users)

        rows["overall"] = score(overall)
        for name, (sums, lengths) in windows.items():
            # Each listen adds a genre distribution summing to 1: sums are listen counts.
            observed = _lookup(sums, event, genre)
            for k in SESSION_SHRINKAGE_GRID:
                q = (observed + k * overall) / (lengths[event] + k)
                rows[f"{name}@{k:g}"] = score(q)
        return rows

    validation = run(train_mask, val_mask)
    best_k = min(SESSION_SHRINKAGE_GRID, key=lambda k: validation[f"session@{k:g}"])
    test = run(train_mask | val_mask, test_mask)
    return {
        "best_shrinkage": best_k,
        "validation": validation,
        "test": test,
        "test_lift": {
            name: float((test["overall"] - test[f"{name}@{best_k:g}"]) / test["overall"])
            for name in ("session", "previous_day")
        },
    }
