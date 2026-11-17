"""Multi-source candidate generation (ADR-016): independent generators, a deterministic merger
that keeps source attribution, and an eligibility filter."""

from app.domains.recommendations.candidate_generation.base import (
    CONTENT_DERIVED_SOURCES,
    SOURCE_ORDER,
    CandidateList,
    Source,
    SourceCandidate,
    SourceStatus,
    run_isolated,
)
from app.domains.recommendations.candidate_generation.candidate_filter import CandidateFilter
from app.domains.recommendations.candidate_generation.candidate_merger import (
    CandidateSet,
    SourceReport,
    merge_candidates,
)

__all__ = [
    "CONTENT_DERIVED_SOURCES",
    "SOURCE_ORDER",
    "CandidateFilter",
    "CandidateList",
    "CandidateSet",
    "Source",
    "SourceCandidate",
    "SourceReport",
    "SourceStatus",
    "merge_candidates",
    "run_isolated",
]
