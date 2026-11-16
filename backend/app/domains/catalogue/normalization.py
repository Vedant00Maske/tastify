"""Text and identifier normalization shared by ingestion, entity resolution and search.

`matching_key` has a vectorized twin in the ML pipelines (pyarrow) for normalizing millions of
listens; the two must stay identical, which tests/unit/catalogue/test_normalization.py checks.
"""

import re
import unicodedata
from datetime import date

ISRC_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
MIN_DURATION_MS = 1_000
MAX_DURATION_MS = 3 * 60 * 60 * 1_000  # longer "tracks" are almost always full albums or mixes

# Parenthesised/bracketed featuring credits: "Song (feat. X)", "Song [ft. X & Y]".
_FEATURING = re.compile(r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring)\s+[^)\]]*[)\]]", re.IGNORECASE)
# Remaster notes: "Song - Remastered 2011", "Song (2009 Remaster)", "Song [Remastered Version]".
_REMASTER = re.compile(
    r"\s*(?:-\s*|[(\[]\s*)(?:\d{4}\s+)?(?:digital(?:ly)?\s+)?remaster(?:ed)?"
    r"(?:\s+\d{4})?(?:\s+version)?\s*[)\]]?\s*$",
    re.IGNORECASE,
)
_NON_ALNUM_RUN = re.compile(r"[^\w]+|_+")


def matching_key(text: str) -> str:
    """Aggressive equality key: accents, case, spacing and punctuation removed.

    "Beyoncé - Halo!" and "beyonce halo" share a key. Characters from non-Latin scripts are kept.
    Names made only of symbols ("?", "!!!!!!!", an artist called "@") keep their lower-cased
    symbols instead, so they stay distinct from each other.
    """
    final_sigma, sigma = chr(0x03C2), chr(0x03C3)  # Greek final and regular sigma
    decomposed = unicodedata.normalize("NFKD", text).lower().replace(final_sigma, sigma)
    # Recompose so scripts like Hangul keep their syllables; accents were already dropped.
    key = unicodedata.normalize("NFC", "".join(ch for ch in decomposed if ch.isalnum()))
    if key:
        return key
    return unicodedata.normalize("NFKC", text).lower().replace(final_sigma, sigma).strip()


def normalize_name(text: str) -> str:
    """Readable normalized form for search columns: lower-case, no accents, single spaces."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    words = _NON_ALNUM_RUN.sub(" ", without_marks.replace("&", " and ").casefold())
    return " ".join(words.split())


def clean_title(title: str) -> str:
    """Remove annotations that do not change the recording: featuring credits and remaster notes.

    Version markers that do change it (live, remix, acoustic, edit) are deliberately kept.
    """
    cleaned = _FEATURING.sub("", title)
    cleaned = _REMASTER.sub("", cleaned)
    return cleaned.strip() or title.strip()


def normalize_isrc(value: str | None) -> str | None:
    """Canonical 12-character ISRC ("US-RC1-76-07839" -> "USRC17607839"), or None if invalid."""
    if not value:
        return None
    candidate = re.sub(r"[\s-]", "", value).upper()
    return candidate if ISRC_PATTERN.match(candidate) else None


def normalize_duration_ms(value: float | int | None) -> int | None:
    """Duration in whole milliseconds, or None when missing or implausible."""
    if value is None:
        return None
    duration = round(value)
    return duration if MIN_DURATION_MS <= duration <= MAX_DURATION_MS else None


def parse_partial_date(value: str | None) -> tuple[date | None, int | None]:
    """Parse MusicBrainz-style partial dates ("1997", "1997-05", "1997-05-21").

    Returns (full date if day precision is known, year if known).
    """
    if not value:
        return None, None
    match = re.fullmatch(r"(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?", value.strip())
    if not match:
        return None, None
    year = int(match.group(1))
    if not 1000 <= year <= 2100:
        return None, None
    if match.group(3):
        try:
            return date(year, int(match.group(2)), int(match.group(3))), year
        except ValueError:
            return None, year
    return None, year
