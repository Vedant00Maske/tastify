"""Registry of external data sources: provenance, licensing, and how to find their files.

Every catalogue record points at one of these sources (data_sources table), so data with usage
restrictions can be filtered out or replaced before any commercial use (ADR-013, docs/DATA_SOURCES.md).
"""

import re
from dataclasses import dataclass
from enum import StrEnum

import httpx

from tastify_ml.data.download import RemoteFile


class UsageRestriction(StrEnum):
    NONE = "none"
    NON_COMMERCIAL = "non_commercial"
    RESEARCH_ONLY = "research_only"


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    homepage_url: str
    license: str
    license_url: str
    usage_restriction: UsageRestriction
    attribution: str | None = None
    notes: str | None = None


MUSICBRAINZ = SourceInfo(
    key="musicbrainz",
    name="MusicBrainz (via the ListenBrainz metadata API and MusicBrainz web service)",
    homepage_url="https://musicbrainz.org",
    license="CC0-1.0 (core data); CC-BY-NC-SA-3.0 (tags, genre associations, ratings)",
    license_url="https://musicbrainz.org/doc/About/Data_License",
    # Genre/tag associations are our main content signal and are non-commercial.
    usage_restriction=UsageRestriction.NON_COMMERCIAL,
    attribution="Data from MusicBrainz (https://musicbrainz.org), MetaBrainz Foundation.",
    notes="API is free for non-commercial use only; commercial use requires a MetaBrainz plan.",
)
MUSICBRAINZ_CANONICAL = SourceInfo(
    key="musicbrainz_canonical",
    name="MusicBrainz canonical data dump",
    homepage_url="https://data.metabrainz.org/pub/musicbrainz/canonical_data/",
    license="CC0-1.0",
    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    usage_restriction=UsageRestriction.NONE,
    notes="Used only to map listen text (artist + title) to recording MBIDs.",
)
LISTENBRAINZ = SourceInfo(
    key="listenbrainz",
    name="ListenBrainz incremental listen dumps and sitewide statistics",
    homepage_url="https://listenbrainz.org",
    license="CC0-1.0",
    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    usage_restriction=UsageRestriction.NONE,
    notes="User names are replaced with keyed hashes on ingest; raw names are never stored.",
)
ACOUSTICBRAINZ = SourceInfo(
    key="acousticbrainz",
    name="AcousticBrainz low-level feature dumps (2022-06-23, final)",
    homepage_url="https://acousticbrainz.org",
    license="CC0-1.0",
    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
    usage_restriction=UsageRestriction.NONE,
    notes="Project discontinued in 2022; features cover recordings submitted before then.",
)
FMA = SourceInfo(
    key="fma",
    name="Free Music Archive dataset (fma_metadata)",
    homepage_url="https://github.com/mdeff/fma",
    license="CC-BY-4.0 (metadata); Echonest-derived features: licence unstated",
    license_url="https://creativecommons.org/licenses/by/4.0/",
    usage_restriction=UsageRestriction.RESEARCH_ONLY,
    attribution="Defferrard et al., FMA: A Dataset for Music Analysis, ISMIR 2017.",
    notes="Dataset is 'meant for research purposes'; audio not downloaded.",
)

ALL_SOURCES = (MUSICBRAINZ, MUSICBRAINZ_CANONICAL, LISTENBRAINZ, ACOUSTICBRAINZ, FMA)

METABRAINZ_DATA = "https://data.metabrainz.org/pub/musicbrainz"
FMA_METADATA = RemoteFile(
    url="https://os.unil.cloud.switch.ch/fma/fma_metadata.zip",
    filename="fma_metadata.zip",
    sha1="f0df49ffe5f2a6008d7dc83c6915b31835dfe733",  # published in the FMA README
)
ACOUSTICBRAINZ_DIR = f"{METABRAINZ_DATA}/acousticbrainz/dumps/acousticbrainz-lowlevel-features-20220623"
ACOUSTICBRAINZ_PARTS = ("rhythm", "lowlevel")

_HREF = re.compile(r'href="([^"?]+)"')


def list_directory(client: httpx.Client, url: str) -> list[str]:
    """Entries of a web server directory index, without the parent link."""
    response = client.get(url.rstrip("/") + "/")
    response.raise_for_status()
    return [href for href in _HREF.findall(response.text) if not href.startswith("..")]


def published_sha256(client: httpx.Client, file_url: str) -> str:
    response = client.get(f"{file_url}.sha256")
    response.raise_for_status()
    return response.text.split()[0]


# Each day also gets a near-empty incremental dump covering a zero-length window; skip those.
MIN_DAILY_DUMP_BYTES = 10_000_000


def latest_listen_dumps(client: httpx.Client, days: int) -> list[RemoteFile]:
    """The `days` most recent daily ListenBrainz incremental listen dumps, newest first."""
    base = f"{METABRAINZ_DATA}/listenbrainz/incremental"
    directories = sorted(
        (d.rstrip("/") for d in list_directory(client, base) if d.endswith("-incremental/")),
        reverse=True,
    )
    files: list[RemoteFile] = []
    for directory in directories:
        for name in list_directory(client, f"{base}/{directory}"):
            if not (name.startswith("listenbrainz-listens-dump-") and name.endswith(".tar.zst")):
                continue
            url = f"{base}/{directory}/{name}"
            size = int(client.head(url).headers.get("content-length", 0))
            if size >= MIN_DAILY_DUMP_BYTES:
                files.append(RemoteFile(url, name, sha256=published_sha256(client, url)))
        if len(files) >= days:
            break
    return files[:days]


def latest_canonical_dump(client: httpx.Client) -> RemoteFile:
    base = f"{METABRAINZ_DATA}/canonical_data"
    directory = max(d.rstrip("/") for d in list_directory(client, base) if d.endswith("/"))
    name = next(
        n for n in list_directory(client, f"{base}/{directory}") if n.endswith(".tar.zst")
    )
    url = f"{base}/{directory}/{name}"
    return RemoteFile(url, name, sha256=published_sha256(client, url))


def acousticbrainz_feature_dumps(client: httpx.Client) -> list[RemoteFile]:
    response = client.get(f"{ACOUSTICBRAINZ_DIR}/sha256sums")
    response.raise_for_status()
    checksums = {
        line.split()[1].lstrip("*"): line.split()[0]
        for line in response.text.splitlines()
        if line.strip()
    }
    files = []
    for part in ACOUSTICBRAINZ_PARTS:
        name = f"acousticbrainz-lowlevel-features-20220623-{part}.tar.zst"
        files.append(RemoteFile(f"{ACOUSTICBRAINZ_DIR}/{name}", name, sha256=checksums.get(name)))
    return files
