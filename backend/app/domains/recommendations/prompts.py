"""Reading a playlist prompt ("indie rock with electronic influence, no metal, 90s") into a
structured intent (Milestone 6, spec FR-016; ADR-019).

Deterministic and explainable on purpose: every part of the intent comes from a word or phrase
the user typed, the result lists what was understood and what was ignored, and ranking uses only
catalogue evidence (spec §9: "Scores and reasons must be based on actual model outputs and
recorded evidence"). No language model is involved.

Understood: catalogue genres (longest phrase first, with a few common spellings), the eight
moods and their everyday words, artists after cues ("like Radiohead", "similar to …", "no
Drake"), tempo ("slow", "fast", "120 bpm"), energy ("chill", "danceable"), era ("90s", "before
2000", "recent"), popularity ("hidden gems", "hits") and familiarity ("new artists",
"favourites"). Negations ("no", "without", "not", "except") exclude genres and artists.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.domains.catalogue.normalization import normalize_name

MAX_PHRASE = 4  # words in the longest genre or artist phrase looked up

# Everyday spellings -> catalogue genre names (used only when that genre exists).
GENRE_SYNONYMS = {
    "hiphop": "hip hop",
    "hip-hop": "hip hop",
    "rap": "hip hop",
    "rnb": "contemporary r&b",
    "r and b": "contemporary r&b",
    "lofi": "lo-fi",
    "edm": "electronic dance music",
    "electronica": "electronic",
    "indie": "indie rock",
}

MOOD_WORDS = {
    "midnight-drive": ("midnight drive", "night drive", "driving", "midnight", "late night"),
    "deep-focus": ("deep focus", "focus", "study", "studying", "concentration", "coding"),
    "rainy-afternoon": ("rainy afternoon", "rainy", "rain"),
    "feel-good": ("feel good", "feel-good", "happy", "sunny", "uplifting", "cheerful"),
    "melancholic-hours": ("melancholic", "melancholy", "sad", "heartbreak", "moody"),
    "slow-sunday": ("slow sunday", "sunday", "lazy", "relaxing", "relaxed"),
    "workout-energy": ("workout", "gym", "running", "training", "pump up"),
    "after-hours": ("after hours", "party", "club", "clubbing"),
}

NEGATIONS = ("no", "without", "not", "except", "minus", "avoid")
ARTIST_CUES = (
    "similar to",
    "sounds like",
    "in the style of",
    "artists like",
    "music like",
    "songs like",
    "like",
    "inspired by",
    "by",
)
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "the",
        "some",
        "of",
        "for",
        "with",
        "to",
        "me",
        "my",
        "i",
        "want",
        "need",
        "give",
        "make",
        "play",
        "please",
        "playlist",
        "mix",
        "music",
        "songs",
        "song",
        "tracks",
        "track",
        "something",
        "stuff",
        "kind",
        "sort",
        "type",
        "vibe",
        "vibes",
        "feel",
        "feeling",
        "influence",
        "influences",
        "influenced",
        "touch",
        "hint",
        "bit",
        "little",
        "more",
        "less",
        "lots",
        "lot",
        "very",
        "really",
        "mostly",
        "mainly",
        "that",
        "is",
        "are",
        "be",
        "in",
        "on",
        "at",
        "from",
        "or",
        "but",
        "plus",
        "mood",
        "moods",
        "style",
        "styles",
        "sound",
        "sounds",
        "good",
        "great",
        "best",
        "nice",
    ]
)


@dataclass
class ParsedPrompt:
    genres: list[str] = field(default_factory=list)
    excluded_genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    artist_phrases: list[str] = field(default_factory=list)
    excluded_artist_phrases: list[str] = field(default_factory=list)
    tempo: tuple[float | None, float | None] = (None, None)
    danceability: tuple[float | None, float | None] = (None, None)
    years: tuple[int | None, int | None] = (None, None)
    popularity: str | None = None  # "lesser_known" or "popular"
    exploration: float | None = None
    ignored: list[str] = field(default_factory=list)

    @property
    def anchored(self) -> bool:
        """Whether there is something to build a playlist from."""
        return bool(self.genres or self.moods or self.artist_phrases)


def _words(text: str) -> list[str]:
    return normalize_name(text.replace("&", " and ")).split()


def _genre_key(name: str) -> str:
    return " ".join(_words(name))


def _decade(token: str, current_year: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"(?:(19|20)|')?(\d)0s", token)
    if not match:
        return None
    century, digit = match.group(1), int(match.group(2))
    if century is None:
        century = "20" if digit * 10 + 2000 <= current_year else "19"
    start = int(century) * 100 + digit * 10
    return start, start + 9


def parse(prompt: str, genres: Mapping[str, str], current_year: int) -> ParsedPrompt:
    """`genres`: normalized genre phrase -> catalogue genre name (see `genre_vocabulary`)."""
    result = ParsedPrompt()
    text = prompt.lower()

    # Numbers and decades first, on the raw text (normalization would split "120bpm").
    exact_tempo = False
    if bpm := re.search(r"(?:around\s+|about\s+|~\s*)?(\d{2,3})\s*bpm", text):
        value = float(bpm.group(1))
        result.tempo = (value - 8, value + 8)
        exact_tempo = True
        text = text.replace(bpm.group(0), " ")
    # "not too popular" is a popularity wish, not an exclusion.
    if found := re.search(r"\bnot\s+(?:too\s+|very\s+|so\s+)?(?:popular|mainstream|known)", text):
        result.popularity = "lesser_known"
        text = text.replace(found.group(0), " ")
    for pattern, kind in (
        (r"(?:before|until|pre)\s+((?:19|20)\d\d)", "max"),
        (r"(?:after|since|from)\s+((?:19|20)\d\d)", "min"),
    ):
        if found := re.search(pattern, text):
            year = int(found.group(1))
            low, high = result.years
            result.years = (year, high) if kind == "min" else (low, year - 1)
            text = text.replace(found.group(0), " ")

    tokens = _words(text)
    used = [False] * len(tokens)

    def phrase(start: int, length: int) -> str:
        return " ".join(tokens[start : start + length])

    def mark(start: int, length: int) -> None:
        for i in range(start, start + length):
            used[i] = True

    def negated(start: int) -> bool:
        return start > 0 and tokens[start - 1] in NEGATIONS

    # Decades and recency.
    for i, token in enumerate(tokens):
        if used[i]:
            continue
        if decade := _decade(token, current_year):
            result.years = decade
            mark(i, 1)
        elif token in ("recent", "latest", "newest"):
            result.years = (current_year - 3, None)
            mark(i, 1)

    # Genres, longest phrase first (so "classic rock" beats "rock").
    for length in range(MAX_PHRASE, 0, -1):
        for start in range(len(tokens) - length + 1):
            if any(used[start : start + length]):
                continue
            words = phrase(start, length)
            name = genres.get(words)  # aliases are in the vocabulary (genre_vocabulary)
            if name is None:
                continue
            target = result.excluded_genres if negated(start) else result.genres
            if name not in target:
                target.append(name)
            mark(start, length)
            if negated(start):
                used[start - 1] = True

    # Moods, in the order the prompt mentions them (the first sets tempo and energy).
    found_moods: list[tuple[int, str]] = []
    for key, words_list in MOOD_WORDS.items():
        for words in sorted(words_list, key=len, reverse=True):
            parts = words.split()
            for start in range(len(tokens) - len(parts) + 1):
                if tokens[start : start + len(parts)] == parts and not any(
                    used[start : start + len(parts)]
                ):
                    found_moods.append((start, key))
                    mark(start, len(parts))
    for _, key in sorted(found_moods):
        if key not in result.moods:
            result.moods.append(key)

    # Tempo, energy, popularity and familiarity words.
    keywords: dict[tuple[str, ...], str] = {
        ("hidden", "gems"): "lesser_known",
        ("hidden", "gem"): "lesser_known",
        ("deep", "cuts"): "lesser_known",
        ("lesser", "known"): "lesser_known",
        ("underground",): "lesser_known",
        ("obscure",): "lesser_known",
        ("hits",): "popular",
        ("popular",): "popular",
        ("mainstream",): "popular",
        ("new", "artists"): "explore",
        ("new", "to", "me"): "explore",
        ("discover",): "explore",
        ("discoveries",): "explore",
        ("unfamiliar",): "explore",
        ("favourites",): "familiar",
        ("favorites",): "familiar",
        ("familiar",): "familiar",
        ("slow",): "slow",
        ("slower",): "slow",
        ("fast",): "fast",
        ("upbeat",): "fast",
        ("uptempo",): "fast",
        ("energetic",): "fast",
        ("chill",): "calm",
        ("calm",): "calm",
        ("mellow",): "calm",
        ("soft",): "calm",
        ("danceable",): "dance",
        ("groovy",): "dance",
    }
    for phrase_words, meaning in sorted(keywords.items(), key=lambda kv: -len(kv[0])):
        for start in range(len(tokens) - len(phrase_words) + 1):
            if tuple(tokens[start : start + len(phrase_words)]) != phrase_words or any(
                used[start : start + len(phrase_words)]
            ):
                continue
            mark(start, len(phrase_words))
            if meaning in ("lesser_known", "popular"):
                result.popularity = meaning
            elif meaning == "explore":
                result.exploration = 0.8
            elif meaning == "familiar":
                result.exploration = 0.2
            elif meaning == "slow" and not exact_tempo:
                result.tempo = (None, 95.0)
            elif meaning == "fast" and not exact_tempo:
                result.tempo = (120.0, None)
            elif meaning == "calm":
                result.danceability = (None, 0.5)
            elif meaning == "dance":
                result.danceability = (0.6, None)

    # Artists after cues: the longest unused run of words that follows (up to MAX_PHRASE),
    # cut at a conjunction; resolved against the catalogue by the service.
    for cue in sorted(ARTIST_CUES, key=len, reverse=True):
        cue_parts = cue.split()
        for start in range(len(tokens) - len(cue_parts)):
            if tokens[start : start + len(cue_parts)] != cue_parts or any(
                used[start : start + len(cue_parts)]
            ):
                continue
            first = start + len(cue_parts)
            end = first
            while end < len(tokens) and end - first < MAX_PHRASE and not used[end]:
                if tokens[end] in ("and", "or", "but", "with", "plus") and end > first:
                    break
                end += 1
            candidate = tokens[first:end]
            if candidate and not all(word in STOPWORDS for word in candidate):
                result.artist_phrases.append(" ".join(candidate))
                mark(start, end - start)
    # Negated leftovers ("no drake") are artist exclusions to resolve.
    for i, token in enumerate(tokens):
        if token in NEGATIONS and not used[i] and i + 1 < len(tokens) and not used[i + 1]:
            end = i + 1
            while end < len(tokens) and not used[end] and end - i <= MAX_PHRASE:
                if tokens[end] in ("and", "or", "but", "with") and end > i + 1:
                    break
                end += 1
            result.excluded_artist_phrases.append(phrase(i + 1, end - i - 1))
            mark(i, end - i)

    result.ignored = [
        token for i, token in enumerate(tokens) if not used[i] and token not in STOPWORDS
    ]
    return result


def genre_vocabulary(names: list[str]) -> dict[str, str]:
    """Normalized phrase -> catalogue genre name, for `parse`."""
    vocabulary: dict[str, str] = {}
    for name in names:
        key = _genre_key(name)
        if key and len(key.split()) <= MAX_PHRASE:
            vocabulary.setdefault(key, name)
    for alias, target in GENRE_SYNONYMS.items():
        key = _genre_key(target)
        if key in vocabulary:
            vocabulary.setdefault(_genre_key(alias), vocabulary[key])
    return vocabulary
