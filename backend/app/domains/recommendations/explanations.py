"""Human-readable reasons built only from recorded evidence (spec section 9: scores and reasons must
reflect actual model outputs). Each function receives the facts behind a score and states them."""

from collections.abc import Mapping, Sequence

SHARED_GENRES_SHOWN = 2
# Typographic quotes and the multiplication sign, as code points (ruff RUF001).
_OPEN, _CLOSE, _TIMES = chr(0x201C), chr(0x201D), chr(0x00D7)


def shared_genres(
    seed: Mapping[str, float], candidate: Mapping[str, float], limit: int = SHARED_GENRES_SHOWN
) -> list[str]:
    """Genres present in both profiles, strongest common weight first (ties by name)."""
    common = seed.keys() & candidate.keys()
    return sorted(common, key=lambda genre: (-min(seed[genre], candidate[genre]), genre))[:limit]


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def similar_track_reason(
    seed_title: str,
    similarity: float,
    genres: Sequence[str],
    same_artist_name: str | None = None,
    same_decade: int | None = None,
) -> str:
    parts: list[str] = []
    if same_artist_name:
        parts.append(f"Also by {same_artist_name}")
    if genres:
        parts.append(f"shares {_join(genres)} with {_OPEN}{seed_title}{_CLOSE}")
    elif same_decade is not None:
        parts.append(f"from the same decade ({same_decade}s) as {_OPEN}{seed_title}{_CLOSE}")
    else:
        parts.append(f"similar overall profile to {_OPEN}{seed_title}{_CLOSE}")
    text = "; ".join(parts)
    return f"{text[0].upper()}{text[1:]} (similarity {similarity:.2f})"


def similar_artist_reason(seed_artist: str, similarity: float, genres: Sequence[str]) -> str:
    text = f"By an artist similar to {seed_artist} (similarity {similarity:.2f})"
    return f"{text}; shares {_join(genres)}" if genres else text


def genre_reason(genre: str, affinity: float, listeners: int) -> str:
    return f"Popular {genre} track ({listeners:,} listeners; genre match {affinity:.2f})"


def popular_reason(listeners: int, window_days: int) -> str:
    return f"Played by {listeners:,} listeners in the last {window_days} days"


def trending_reason(recent_listeners: int, growth: float, recent_days: int) -> str:
    return (
        f"Listeners up {growth:.1f}{_TIMES} in the last {recent_days} days "
        f"({recent_listeners:,} recent listeners)"
    )


# --- Milestone 3: personalized reasons -------------------------------------------------------


def seed_similarity_reason(seed_title: str, similarity: float, plays: int) -> str:
    played = f"you played {plays:,} times" if plays > 1 else "you played"
    return f"Similar to {_OPEN}{seed_title}{_CLOSE}, which {played} (similarity {similarity:.2f})"


def familiar_artist_reason(artist: str, affinity: float) -> str:
    return f"More from {artist}, one of your top artists (affinity {affinity:.2f})"


def co_listened_reason(seed_title: str) -> str:
    return f"Listeners who play {_OPEN}{seed_title}{_CLOSE} also play this"


def collaborative_reason(score_rank: int) -> str:
    return f"Popular with listeners whose taste overlaps yours (collaborative rank {score_rank})"


def new_artist_reason(artist: str, genres: Sequence[str], similarity: float) -> str:
    if genres:
        return f"New artist for you: {artist}, matching your taste for {_join(genres)}"
    return (
        f"New artist for you: {artist}, close to your taste profile (similarity {similarity:.2f})"
    )


def profile_reason(genres: Sequence[str], similarity: float) -> str:
    if genres:
        return f"Matches your taste for {_join(genres)} (profile similarity {similarity:.2f})"
    return f"Matches your taste profile (similarity {similarity:.2f})"


def artist_radio_reason(artist: str, listeners: int) -> str:
    return f"By {artist} ({listeners:,} listeners)"


# --- Milestone 4 ---------------------------------------------------------------------------------


def mood_reason(mood: str, genre: str, tempo: float | None, taste: float | None) -> str:
    detail = f"{genre}, {tempo:.0f} BPM" if tempo else genre
    text = f"Fits {mood}: {detail}"
    return f"{text}; close to your taste ({taste:.2f})" if taste is not None and taste > 0 else text


def hidden_gem_reason(base: str, listeners: int) -> str:
    return f"{base}. A hidden gem: {listeners:,} listeners in the last 14 days"


def surprise_reason(base: str) -> str:
    return f"Something new for you. {base}"


def playlist_fit_reason(playlist: str, similarity: float) -> str:
    return f"Fits the sound of {_OPEN}{playlist}{_CLOSE} (similarity {similarity:.2f})"
