import zipfile
from pathlib import Path

import pyarrow as pa
import pytest
from pydantic import ValidationError

from soniqueo_ml.data.ingestion import acousticbrainz, fma
from tests.conftest import write_tar_zst

# tracks.csv uses a two-row header (entity, field); echonest.csv a three-row header.
TRACKS_CSV = """,album,album,album,album,artist,artist,artist,track,track,track,track
,id,title,type,date_released,id,name,active_year_begin,title,duration,genres,genre_top
track_id,,,,,,,,,,,
2,1,AWOL - A Way Of Life,Album,2009-01-05 00:00:00,1,AWOL,2006-01-01 00:00:00,Food,168,[21],Hip-Hop
5,1,AWOL - A Way Of Life,Album,2009-01-05 00:00:00,1,AWOL,,This World,206,"[21, 76]",Hip-Hop
10,6,Constant Hitmaker,,,6,Kurt Vile,,Freeway,161,[10],Pop
11,7,,,,7,,,No Artist Name,100,[],
"""
ECHONEST_CSV = """,echonest,echonest,echonest,echonest,echonest,echonest,echonest
,audio_features,audio_features,audio_features,audio_features,audio_features,audio_features,metadata
,acousticness,danceability,energy,instrumentalness,tempo,valence,artist_name
track_id,,,,,,,
2,0.416,0.676,0.634,0.010,165.922,0.576,AWOL
5,0.374,0.528,0.817,0.001,126.957,0.269,AWOL
"""
GENRES_CSV = """genre_id,#tracks,parent,title,top_level
10,13845,0,Pop,10
21,8389,0,Hip-Hop,21
76,1200,21,Experimental Hip-Hop,21
"""


@pytest.fixture
def archive(tmp_path: Path) -> zipfile.ZipFile:
    path = tmp_path / "fma_metadata.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("fma_metadata/tracks.csv", TRACKS_CSV)
        zf.writestr("fma_metadata/echonest.csv", ECHONEST_CSV)
        zf.writestr("fma_metadata/genres.csv", GENRES_CSV)
    return fma.open_metadata(path)


def test_genres_keep_their_hierarchy(archive: zipfile.ZipFile) -> None:
    genres = {g.genre_id: g for g in fma.read_genres(archive)}

    assert genres[76].parent_id == 21
    assert genres[21].parent_id is None


def test_echonest_features_are_indexed_by_track(archive: zipfile.ZipFile) -> None:
    features = fma.read_echonest(archive)

    assert list(features.index) == [2, 5]
    assert features.loc[2, "tempo"] == pytest.approx(165.922)
    assert list(features.columns) == list(fma.ECHONEST_FEATURES)


def test_tracks_become_source_tracks(archive: zipfile.ZipFile) -> None:
    genres = {g.genre_id: g for g in fma.read_genres(archive)}
    tracks = fma.read_tracks(archive)

    track = fma.parse_track(5, dict(fma.iter_rows(tracks))[5], genres)

    assert (track.provider, track.external_id, track.title) == ("fma", "5", "This World")
    assert track.duration_ms == 206_000
    assert track.credits[0].artist.external_id == "1"
    assert track.album is not None
    assert (track.album.title, track.album.release_date) == ("AWOL - A Way Of Life", "2009-01-05")
    assert [g.name for g in track.genres] == ["Hip-Hop", "Experimental Hip-Hop"]


def test_artist_begin_year_and_missing_album(archive: zipfile.ZipFile) -> None:
    genres = {g.genre_id: g for g in fma.read_genres(archive)}
    tracks = fma.read_tracks(archive)

    assert (
        fma.parse_track(2, dict(fma.iter_rows(tracks))[2], genres).credits[0].artist.begin_year
        == 2006
    )
    assert fma.parse_track(10, dict(fma.iter_rows(tracks))[10], genres).album is not None
    assert fma.read_tracks(archive, track_ids=fma.read_echonest(archive).index).index.tolist() == [
        2,
        5,
    ]


def test_tracks_without_an_artist_name_are_rejected(archive: zipfile.ZipFile) -> None:
    tracks = fma.read_tracks(archive)

    with pytest.raises(ValidationError):
        fma.parse_track(11, dict(fma.iter_rows(tracks))[11], {})


def test_acousticbrainz_keeps_first_submission_of_wanted_recordings(tmp_path: Path) -> None:
    rhythm = write_tar_zst(
        tmp_path / "rhythm.tar.zst",
        {
            "d/rhythm.csv": (
                b"mbid,submission_offset,bpm,bpm_histogram_first_peak_bpm_mean,"
                b"danceability,onset_rate\r\n"
                b"rec-a,0,120.5,120,1.5,2.8\r\n"
                b"rec-a,1,60.0,60,0.3,1.0\r\n"
                b"rec-b,0,400.0,400,4.2,3.0\r\n"
                b"rec-x,0,99.0,99,1.0,1.0\r\n"
            )
        },
    )
    lowlevel = write_tar_zst(
        tmp_path / "lowlevel.tar.zst",
        {
            "d/lowlevel.csv": b"mbid,submission_offset,average_loudness,dynamic_complexity\r\n"
            b"rec-a,0,0.7,5.6\r\n"
        },
    )
    wanted = pa.array(["rec-a", "rec-b"])

    records = acousticbrainz.combine_features(
        acousticbrainz.read_part(rhythm, "rhythm", wanted),
        acousticbrainz.read_part(lowlevel, "lowlevel", wanted),
    )

    by_mbid = {r["mbid"]: r for r in records}
    assert set(by_mbid) == {"rec-a", "rec-b"}
    assert by_mbid["rec-a"] == {
        "mbid": "rec-a",
        "tempo": 120.5,
        "danceability": 0.5,
        "onset_rate": 2.8,
        "loudness": 0.7,
    }
    assert by_mbid["rec-b"]["tempo"] is None  # implausible BPM
    assert by_mbid["rec-b"]["danceability"] == 1.0  # clipped
    assert by_mbid["rec-b"]["loudness"] is None


def test_echonest_values_out_of_range_are_rejected() -> None:
    values = {
        "tempo": 0.0,  # Echonest's "unknown"
        "energy": 0.5,
        "danceability": 1.2,
        "valence": float("nan"),
        "acousticness": 0.1,
        "instrumentalness": 0.0,
    }

    cleaned, rejected = fma.validate_features(values)

    assert sorted(rejected) == ["danceability", "tempo", "valence"]
    assert cleaned["tempo"] is None
    assert cleaned["energy"] == 0.5
    assert cleaned["instrumentalness"] == 0.0
