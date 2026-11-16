from datetime import date

import pytest

from app.domains.catalogue.normalization import (
    clean_title,
    matching_key,
    normalize_duration_ms,
    normalize_isrc,
    normalize_name,
    parse_partial_date,
)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Beyoncé - Halo!", "beyonce halo"),
        ("AC/DC", "acdc"),
        ("  Mötley   Crüe ", "MOTLEY CRUE"),
        ("".join(map(chr, (0xFF21, 0xFF22, 0xFF23))), "abc"),  # full-width "ABC"
        ("ΟΔΥΣΣΕΑΣ", "οδυσσεασ"),  # Greek final sigma
    ],
)
def test_matching_key_ignores_case_accents_spacing_and_punctuation(left: str, right: str) -> None:
    assert matching_key(left) == matching_key(right)


def test_matching_key_keeps_non_latin_scripts() -> None:
    assert matching_key("乡愁 四韵") == "乡愁四韵"
    assert matching_key("방탄소년단") == "방탄소년단"


def test_symbol_only_names_keep_a_distinctive_key() -> None:
    # Real titles/artists: "?" , "!!!!!!!" (Billie Eilish), an artist called "@".
    assert matching_key("?") == "?"
    assert matching_key(" ★ ") == "★"
    assert matching_key("!!!!!!!") != matching_key("?")
    assert matching_key("") == ""


def test_matching_key_distinguishes_different_titles() -> None:
    assert matching_key("Halo") != matching_key("Hello")


def test_normalize_name_produces_searchable_words() -> None:
    assert normalize_name("Simon & Garfunkel") == "simon and garfunkel"
    assert normalize_name("Sigur Rós — Hoppípolla") == "sigur ros hoppipolla"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Halo (feat. Somebody)", "Halo"),
        ("Halo [ft. A & B]", "Halo"),
        ("Come Together - Remastered 2009", "Come Together"),
        ("Come Together (2019 Remaster)", "Come Together"),
        ("Come Together [Remastered Version]", "Come Together"),
        ("Halo (Live)", "Halo (Live)"),
        ("Halo - Radio Edit", "Halo - Radio Edit"),
        ("Halo (Acoustic Remix)", "Halo (Acoustic Remix)"),
    ],
)
def test_clean_title_removes_only_annotations_that_keep_the_recording(
    title: str, expected: str
) -> None:
    assert clean_title(title) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("USRC17607839", "USRC17607839"),
        ("us-rc1-76-07839", "USRC17607839"),
        (" GB AHT 16 00302 ", "GBAHT1600302"),
        ("USRC1760783", None),  # too short
        ("12RC17607839", None),  # country code must be letters
        ("", None),
        (None, None),
    ],
)
def test_normalize_isrc(raw: str | None, expected: str | None) -> None:
    assert normalize_isrc(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (135171, 135171),
        (135171.6, 135172),
        (0, None),
        (999, None),
        (11_000_000, None),
        (None, None),
    ],
)
def test_normalize_duration_rejects_missing_and_implausible_values(
    raw: float | None, expected: int | None
) -> None:
    assert normalize_duration_ms(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1997-05-21", (date(1997, 5, 21), 1997)),
        ("1997-05", (None, 1997)),
        ("1997", (None, 1997)),
        ("1997-02-30", (None, 1997)),
        ("0000", (None, None)),
        ("May 1997", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_partial_date(raw: str | None, expected: tuple[date | None, int | None]) -> None:
    assert parse_partial_date(raw) == expected
