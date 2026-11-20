import pytest
from pydantic import ValidationError

from soniqueo_ml.data.ingestion.listenbrainz_metadata import parse_recording

# Shape of a real /1/metadata/recording/ response entry (trimmed).
PAYLOAD = {
    "artist": {
        "artist_credit_id": 1,
        "name": "Jay-Z feat. Beyoncé",
        "artists": [
            {
                "artist_mbid": "a-jay",
                "name": "Jay-Z",
                "join_phrase": " feat. ",
                "type": "Person",
                "area": "United States",
                "begin_year": 1969,
            },
            {"artist_mbid": "a-bey", "name": "Beyoncé", "join_phrase": "", "type": "Person"},
        ],
    },
    "recording": {
        "name": "'03 Bonnie & Clyde",
        "length": 205000,
        "isrcs": ["usuyg0230111", "not-an-isrc"],
        "first_release_date": "2002-10-10",
        "rels": [],
    },
    "release": {
        "mbid": "rel-1",
        "name": "The Blueprint 2",
        "release_group_mbid": "rg-1",
        "year": 2002,
    },
    "tag": {
        "artist": [
            {"artist_mbid": "a-jay", "tag": "hip hop", "count": 9, "genre_mbid": "g-hiphop"},
            {"artist_mbid": "a-jay", "tag": "1990s", "count": 2},
            {"artist_mbid": "a-bey", "tag": "r&b", "count": 4, "genre_mbid": "g-rnb"},
        ],
        "recording": [{"tag": "hip hop", "count": 1, "genre_mbid": "g-hiphop"}],
        "release_group": [{"tag": "east coast hip hop", "count": 2, "genre_mbid": "g-ech"}],
    },
}


def test_full_payload_becomes_a_source_track() -> None:
    track = parse_recording("rec-1", PAYLOAD)

    assert track.provider == "musicbrainz"
    assert track.external_id == "rec-1"
    assert track.title == "'03 Bonnie & Clyde"
    assert track.duration_ms == 205000
    assert track.isrcs == ["USUYG0230111"]  # normalized; the invalid one is dropped
    assert track.release_date == "2002-10-10"
    assert [(c.credited_name, c.join_phrase) for c in track.credits] == [
        ("Jay-Z", " feat. "),
        ("Beyoncé", ""),
    ]
    assert track.album is not None
    assert (track.album.external_id, track.album.title, track.album.release_date) == (
        "rg-1",
        "The Blueprint 2",
        "2002",
    )
    assert [g.name for g in track.album.genres] == ["east coast hip hop"]
    assert [g.name for g in track.genres] == ["hip hop"]


def test_artist_tags_are_attached_to_the_right_artist() -> None:
    track = parse_recording("rec-1", PAYLOAD)

    jay, beyonce = (credit.artist for credit in track.credits)
    assert [(g.name, g.count, g.musicbrainz_id) for g in jay.genres] == [
        ("hip hop", 9, "g-hiphop"),
        ("1990s", 2, None),
    ]
    assert [g.name for g in beyonce.genres] == ["r&b"]
    assert jay.begin_year == 1969


def test_missing_release_means_no_album() -> None:
    payload = {**PAYLOAD, "release": {}}

    assert parse_recording("rec-1", payload).album is None


def test_recording_without_artists_is_rejected() -> None:
    payload = {**PAYLOAD, "artist": {"artists": []}}

    with pytest.raises(ValidationError):
        parse_recording("rec-1", payload)


def test_unknown_recording_is_rejected() -> None:
    with pytest.raises(KeyError):
        parse_recording("rec-404", {})
