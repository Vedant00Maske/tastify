import pyarrow as pa

from tastify_ml.pipelines.catalogue import first_per_track, select_seeds


def test_features_keep_one_row_per_canonical_track() -> None:
    rows = [
        {"track_id": "t1", "tempo": 120.0},
        {"track_id": "t2", "tempo": 90.0},
        {"track_id": "t1", "tempo": 60.0},  # a second source record linked to t1
    ]

    assert first_per_track(rows) == [
        {"track_id": "t1", "tempo": 120.0},
        {"track_id": "t2", "tempo": 90.0},
    ]


def test_seeds_are_the_most_listened_recordings_above_the_listener_floor() -> None:
    popularity = pa.table(
        {
            "recording_mbid": ["a", "b", "c", "d"],
            "listeners": [50, 9, 3, 2],
            "listens": [90, 20, 5, 9],
        }
    )

    assert select_seeds(popularity, size=2, min_listeners=3) == ["a", "b"]
    assert select_seeds(popularity, size=10, min_listeners=3) == ["a", "b", "c"]
