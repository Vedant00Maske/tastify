"""Online experiments (Milestone 6; ADR-019): deterministic assignment and outcome statistics.

A running experiment splits users between weighted variants by hashing (experiment, user), so a
user always sees the same variant without anything being stored. Each variant carries the
parameters it changes (for example `context_weight`). Outcomes come from feedback that carries
the request id of the response it was given on: positive (like, save, playlist add) and
negative (dislike) actions per recommended item. Variants are compared with Wilson intervals
and a two-proportion z-test; small samples are reported as such, not as wins.
"""

import hashlib
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

POSITIVE_FEEDBACK = ("like", "save", "playlist_add")
NEGATIVE_FEEDBACK = ("dislike",)
MIN_ITEMS_FOR_VERDICT = 1000  # per variant
Z_95 = 1.959964


@dataclass(frozen=True)
class Variant:
    name: str
    weight: float
    params: Mapping[str, Any]


@dataclass(frozen=True)
class Assignment:
    experiment: str
    variant: str
    params: Mapping[str, Any]


def parse_variants(raw: Sequence[Mapping[str, Any]]) -> list[Variant]:
    variants = [
        Variant(str(v["name"]), float(v.get("weight", 1.0)), dict(v.get("params") or {}))
        for v in raw
    ]
    if len(variants) < 2:
        raise ValueError("an experiment needs at least two variants")
    if len({v.name for v in variants}) != len(variants):
        raise ValueError("variant names must be unique")
    if any(v.weight <= 0 for v in variants):
        raise ValueError("variant weights must be positive")
    return variants


def bucket(experiment: str, user_id: uuid.UUID) -> float:
    """A stable number in [0, 1) for this user in this experiment."""
    digest = hashlib.sha256(f"{experiment}:{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign(experiment: str, variants: Sequence[Variant], user_id: uuid.UUID) -> Assignment:
    total = sum(v.weight for v in variants)
    point = bucket(experiment, user_id) * total
    for variant in variants:
        point -= variant.weight
        if point < 0:
            return Assignment(experiment, variant.name, variant.params)
    last = variants[-1]
    return Assignment(experiment, last.name, last.params)


# --- statistics -------------------------------------------------------------------------------


def wilson(successes: int, trials: int, z: float = Z_95) -> tuple[float, float]:
    if trials == 0:
        return 0.0, 0.0
    p = successes / trials
    centre = (p + z * z / (2 * trials)) / (1 + z * z / trials)
    margin = (z / (1 + z * z / trials)) * math.sqrt(
        p * (1 - p) / trials + z * z / (4 * trials * trials)
    )
    return max(0.0, centre - margin), min(1.0, centre + margin)


def two_proportion_p_value(s1: int, n1: int, s2: int, n2: int) -> float | None:
    """Two-sided p-value that the two rates are equal (normal approximation)."""
    if n1 == 0 or n2 == 0:
        return None
    pooled = (s1 + s2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return None
    z = (s1 / n1 - s2 / n2) / se
    return math.erfc(abs(z) / math.sqrt(2))


@dataclass(frozen=True)
class VariantOutcome:
    name: str
    users: int
    requests: int
    items: int
    positive: int
    negative: int

    @property
    def positive_rate(self) -> float:
        return self.positive / self.items if self.items else 0.0

    @property
    def negative_rate(self) -> float:
        return self.negative / self.items if self.items else 0.0


def compare(control: VariantOutcome, treatment: VariantOutcome) -> dict[str, Any]:
    """Positive and negative feedback rates per recommended item, with intervals and a verdict
    that refuses to call a winner on small samples."""
    p_pos = two_proportion_p_value(
        treatment.positive, treatment.items, control.positive, control.items
    )
    p_neg = two_proportion_p_value(
        treatment.negative, treatment.items, control.negative, control.items
    )
    enough = min(control.items, treatment.items) >= MIN_ITEMS_FOR_VERDICT
    if not enough:
        verdict = "not enough data"
    elif p_pos is not None and p_pos < 0.05:
        better = treatment.positive_rate > control.positive_rate
        verdict = f"{treatment.name} {'better' if better else 'worse'} than {control.name}"
    else:
        verdict = "no significant difference"
    return {
        "control": control.name,
        "treatment": treatment.name,
        "positive_rate": {
            control.name: control.positive_rate,
            treatment.name: treatment.positive_rate,
        },
        "positive_ci": {
            control.name: wilson(control.positive, control.items),
            treatment.name: wilson(treatment.positive, treatment.items),
        },
        "positive_p_value": p_pos,
        "negative_rate": {
            control.name: control.negative_rate,
            treatment.name: treatment.negative_rate,
        },
        "negative_p_value": p_neg,
        "verdict": verdict,
    }
