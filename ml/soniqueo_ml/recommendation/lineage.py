"""Model-training lineage: which signals from which sources, under which licence, each model
uses (ADR-016; spec: keep source-level provenance so models can be retrained on commercially
permitted signals).

MusicBrainz is split by component: its core data (recording and artist identities, titles,
release metadata) is CC0, while tags and genre associations are CC BY-NC-SA. The catalogue
records carry the source-level restriction (`non_commercial`); lineage records the component a
model actually uses.
"""

from collections.abc import Iterable, Sequence
from typing import Any

RESTRICTION_ORDER = ("none", "non_commercial", "research_only")

SIGNALS: dict[str, dict[str, Any]] = {
    "listening events": {
        "source": "listenbrainz",
        "licence": "CC0-1.0",
        "restriction": "none",
    },
    "listen-to-recording mapping": {
        "source": "musicbrainz_canonical",
        "licence": "CC0-1.0",
        "restriction": "none",
    },
    "recording and artist identities, release metadata": {
        "source": "musicbrainz",
        "licence": "CC0-1.0 (MusicBrainz core data)",
        "restriction": "none",
    },
    "genre tags": {
        "source": "musicbrainz",
        "licence": "CC-BY-NC-SA-3.0 (MusicBrainz tags and genre associations)",
        "restriction": "non_commercial",
    },
    "audio features": {
        "source": "acousticbrainz",
        "licence": "CC0-1.0",
        "restriction": "none",
    },
    "SONIQUEO user interactions": {
        "source": "soniqueo",
        "licence": "user data under the SONIQUEO privacy policy",
        "restriction": "none",
    },
}

MODEL_SIGNALS: dict[str, tuple[str, ...]] = {
    "popularity": ("listening events", "listen-to-recording mapping"),
    "collaborative": (
        "listening events",
        "listen-to-recording mapping",
        "recording and artist identities, release metadata",
    ),
    "content": ("recording and artist identities, release metadata", "genre tags"),
    "hybrid": (
        "listening events",
        "listen-to-recording mapping",
        "recording and artist identities, release metadata",
        "genre tags",
        "SONIQUEO user interactions",
    ),
    "hybrid-cc0": (
        "listening events",
        "listen-to-recording mapping",
        "recording and artist identities, release metadata",
        "SONIQUEO user interactions",
    ),
}


def most_restrictive(restrictions: Iterable[str]) -> str:
    return max(restrictions, key=RESTRICTION_ORDER.index, default="none")


def lineage(
    model: str, upstream: dict[str, str] | None = None, extra: Sequence[str] = ()
) -> dict[str, Any]:
    names = (*MODEL_SIGNALS[model], *extra)
    signals = [{"signal": name, **SIGNALS[name]} for name in dict.fromkeys(names)]
    restriction = most_restrictive(s["restriction"] for s in signals)
    return {
        "signals": signals,
        "upstream_versions": upstream or {},
        "usage_restriction": restriction,
        "commercial_use": restriction == "none",
    }
