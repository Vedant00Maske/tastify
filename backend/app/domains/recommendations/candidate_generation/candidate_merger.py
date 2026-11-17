"""Merges per-source candidate lists into one deterministic candidate set.

Every item appears once, with its score and rank in every source that found it (NaN / inf
where a source did not), so ranking can use all of them and explanations can say where an item
came from. Rows are ordered by their best rank in any source, then by source order, then by
first appearance: for a fixed input, the merged set is always identical.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

import numpy as np
import numpy.typing as npt

from app.domains.recommendations.candidate_generation.base import (
    SOURCE_ORDER,
    CandidateList,
    Source,
    SourceCandidate,
    SourceStatus,
)

K = TypeVar("K", bound=Hashable)

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class SourceReport:
    source: Source
    status: SourceStatus
    candidates: int
    model_version: str | None
    detail: str | None


@dataclass(frozen=True)
class CandidateSet(Generic[K]):
    items: tuple[K, ...]
    # (n, len(SOURCE_ORDER)): retrieval score and 1-based rank per source; NaN / inf if absent.
    scores: FloatArray
    ranks: FloatArray
    reports: tuple[SourceReport, ...]

    def __len__(self) -> int:
        return len(self.items)

    @staticmethod
    def column(source: Source) -> int:
        return SOURCE_ORDER.index(source)

    def found_by(self, source: Source) -> BoolArray:
        return np.asarray(np.isfinite(self.ranks[:, self.column(source)]))

    def report(self, source: Source) -> SourceReport | None:
        return next((r for r in self.reports if r.source == source), None)

    def attribution(self, row: int) -> list[SourceCandidate[K]]:
        """Every source that found the item at `row`, in source order."""
        versions = {r.source: r.model_version for r in self.reports}
        out: list[SourceCandidate[K]] = []
        for column, source in enumerate(SOURCE_ORDER):
            rank = self.ranks[row, column]
            if np.isfinite(rank):
                out.append(
                    SourceCandidate(
                        self.items[row],
                        source,
                        float(self.scores[row, column]),
                        int(rank),
                        versions.get(source),
                    )
                )
        return out

    def subset(self, rows: IntArray | Sequence[int]) -> "CandidateSet[K]":
        index = np.asarray(rows, dtype=np.int64)
        return CandidateSet(
            tuple(self.items[i] for i in index),
            self.scores[index],
            self.ranks[index],
            self.reports,
        )


def merge_candidates(lists: Sequence[CandidateList[K]]) -> CandidateSet[K]:
    """Union of the lists; at most one list per source (a second one is a programming error)."""
    by_source: dict[Source, CandidateList[K]] = {}
    for candidate_list in lists:
        if candidate_list.source in by_source:
            raise ValueError(f"two candidate lists for source {candidate_list.source}")
        by_source[candidate_list.source] = candidate_list

    row_of: dict[K, int] = {}
    items: list[K] = []
    entries: list[tuple[int, int, int, float]] = []  # (row, column, rank, score)
    for column, source in enumerate(SOURCE_ORDER):
        current = by_source.get(source)
        if current is None or current.status is not SourceStatus.OK:
            continue
        taken: set[K] = set()
        for rank, (item, score) in enumerate(
            zip(current.items, current.scores, strict=True), start=1
        ):
            if item in taken:  # a duplicate inside one list keeps its best (first) rank
                continue
            taken.add(item)
            row = row_of.get(item)
            if row is None:
                row = row_of[item] = len(items)
                items.append(item)
            entries.append((row, column, rank, score))

    n, s = len(items), len(SOURCE_ORDER)
    scores = np.full((n, s), np.nan)
    ranks = np.full((n, s), np.inf)
    for row, column, rank, score in entries:
        scores[row, column] = score
        ranks[row, column] = rank

    reports = tuple(
        SourceReport(
            source,
            by_source[source].status,
            len(by_source[source]),
            by_source[source].model_version,
            by_source[source].detail,
        )
        for source in SOURCE_ORDER
        if source in by_source
    )
    if n == 0:
        return CandidateSet((), scores, ranks, reports)
    best_rank = ranks.min(axis=1)
    best_column = ranks.argmin(axis=1)
    order = np.lexsort((np.arange(n), best_column, best_rank))
    return CandidateSet(tuple(items[i] for i in order), scores[order], ranks[order], reports)
