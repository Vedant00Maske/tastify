import pyarrow as pa
import pytest

from app.domains.catalogue import normalization
from app.domains.catalogue.writer import track_matching_key as python_track_key
from soniqueo_ml.data.normalization import keys

# Deliberately awkward strings: accents, punctuation, scripts, compatibility forms, annotations.
CORPUS = [
    "Beyoncé - Halo!",
    "AC/DC",
    "  Mötley   Crüe ",
    "".join(map(chr, (0xFF21, 0xFF22, 0xFF23))),  # full-width ABC
    "ΟΔΥΣΣΕΑΣ",
    "乡愁 四韵",
    "방탄소년단",
    "Sigur Rós — Hoppípolla",
    "Ñandú № 5 ½",
    "Ǆungla İstanbul ß",
    "Halo (feat. Somebody)",
    "Come Together - Remastered 2009",
    "Come Together (2019 Remaster)",
    "Song [Remastered Version]",
    "Halo (Live)",
    "(feat. Only A Feature)",
    "Remastered",
    "日本語のタイトル" + chr(0xFF08) + "ライブ" + chr(0xFF09),  # full-width parentheses
    "Ünïcödé ŝtŕïñğ",
    "under_score & ampersand",
    "?",
    "!!!!!!!",
    " = ",
    "★",  # black star
    "¥$",  # yen sign + dollar
    "",
]


@pytest.mark.parametrize("text", CORPUS)
def test_vectorized_matching_key_equals_python(text: str) -> None:
    assert keys.matching_key(pa.array([text])).to_pylist() == [normalization.matching_key(text)]


@pytest.mark.parametrize("text", CORPUS)
def test_vectorized_clean_title_equals_python(text: str) -> None:
    assert keys.clean_title(pa.array([text])).to_pylist() == [normalization.clean_title(text)]


def test_vectorized_track_key_equals_python() -> None:
    artists = ["Beyoncé", "The Beatles", "방탄소년단"]
    titles = ["Halo (feat. X)", "Come Together - Remastered 2009", "Dynamite"]

    vectorized = keys.track_matching_key(pa.array(artists), pa.array(titles)).to_pylist()

    assert vectorized == [python_track_key(a, t) for a, t in zip(artists, titles, strict=True)]
