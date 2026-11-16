# Catalogue data quality report

Generated 2026-11-16 13:01 UTC by `python -m tastify_ml catalogue quality`.

## Catalogue

| Measure | Value |
| --- | --- |
| Tracks | 42,952 |
| Artists | 8,865 |
| Albums | 14,252 |
| Genres | 2,296 |
| Tracks with ISRC | 26,314 (61.3%) |
| Tracks with duration | 42,497 (98.9%) |
| Tracks with track/album genres | 38,270 (89.1%) |
| Tracks with any genre (incl. artist) | 41,916 (97.6%) |
| Tracks with audio features | 31,831 (74.1%) |
| Tracks identified by more than one source | 0 |
| Possible duplicates pending review | 100 |

### Tracks by source

| Source | Tracks |
| --- | --- |
| fma | 13,104 |
| musicbrainz | 29,848 |

### Identifiers

| Provider | Match method | Count |
| --- | --- | --- |
| fma | metadata | 24 |
| fma | source | 13,104 |
| isrc | source | 38,472 |
| musicbrainz | isrc | 34 |
| musicbrainz | metadata | 96 |
| musicbrainz | source | 29,848 |

### Audio features

| Source | Version | Tracks |
| --- | --- | --- |
| acousticbrainz | acousticbrainz-lowlevel-2022-06-23 | 18,727 |
| fma_echonest | echonest-fma-2017 | 13,104 |

### Most common genres (track or album level)

rock (16,384), pop (11,914), electronic (10,699), pop rock (7,690), alternative rock (6,739), indie rock (5,109), hip hop (4,897), punk (2,997), synth-pop (2,861), heavy metal (2,779), metal (2,613), hard rock (2,563), folk (2,368), dance-pop (2,283), indie pop (2,236)

## Sources and licences

| Source | Licence | Usage restriction |
| --- | --- | --- |
| acousticbrainz | CC0-1.0 | none |
| fma | CC-BY-4.0 (metadata); Echonest-derived features: licence unstated | research_only |
| listenbrainz | CC0-1.0 | none |
| musicbrainz | CC0-1.0 (core data); CC-BY-NC-SA-3.0 (tags, genre associations, ratings) | non_commercial |
| musicbrainz_canonical | CC0-1.0 | none |

## Latest pipeline runs

| Stage | Source | Status | Statistics |
| --- | --- | --- | --- |
| acousticbrainz | acousticbrainz | succeeded | `{"errors": {}, "recordings_with_features": 18739, "tracks_with_features": 18727}` |
| catalogue | musicbrainz | succeeded | `{"cached": 29971, "created": 29753, "created_for_review": 95, "errors": {"identifier_conflict": 39, "metadata_not_found": 121}, "fetched": 7, "linked": 130, "seeds": 30099}` |
| fma | fma | succeeded | `{"errors": {"feature_out_of_range": 2, "invalid_fma_track": 1}, "updated": 13128}` |
| genres | musicbrainz | succeeded | `{"errors": {}, "genres": 2227}` |
| interactions | listenbrainz | succeeded | `{"errors": {}, "interactions": 6338097, "mapped_listens": 14735829, "tracks": 29822, "users": 39013}` |
| listens | listenbrainz | succeeded | `{"dropped_outside_window": 47754064, "errors": {}, "files_processed": 14, "kept": 20279942, "lines": 68034006}` |
| mapping | musicbrainz_canonical | succeeded | `{"ambiguous_keys": 7913, "canonical_text": 14474971, "client_mbid": 260858, "distinct_listen_keys": 3729115, "errors": {}, "mapped_keys": 1934941, "recordings_heard": 2016867, "total": 20279942, "unmapped": 5544113}` |

## Checks

| Result | Severity | Category | Check | Count |
| --- | --- | --- | --- | --- |
| pass | error | missing track ids | `tracks_without_identifiers`: Tracks with no provider identifier at all (cannot be traced to a source). | 0 |
| pass | error | missing track ids | `tracks_missing_title`: Tracks with an empty title or matching key. | 0 |
| flag | warning | duplicate tracks | `unresolved_duplicates`: Possible duplicates the resolution policy refused to link automatically (pending review). | 100 |
| pass | warning | duplicate tracks | `same_key_same_duration`: Distinct tracks sharing artist/title key and duration within 1 s, with no review record. | 0 |
| pass | error | invalid artist relationships | `tracks_without_credits`: Tracks with no artist credit rows. | 0 |
| pass | error | invalid artist relationships | `primary_artist_not_first_credit`: Tracks whose primary artist differs from the first credited artist. | 0 |
| pass | info | invalid artist relationships | `artists_without_tracks`: Artists not credited on any track (e.g. only referenced by albums). | 0 |
| pass | error | invalid timestamps | `implausible_release_years`: Release years before 1000 or more than a year in the future. | 0 |
| flag | warning | invalid timestamps | `announced_future_releases`: Release dates later than today (announced releases already being streamed). | 15 |
| flag | warning | invalid timestamps | `track_released_before_artist_began`: Tracks released more than a year before their artist's begin year. | 4 |
| pass | error | invalid duration | `invalid_duration`: Durations outside 1 s to 3 h (also enforced by a CHECK constraint). | 0 |
| flag | warning | invalid duration | `missing_duration`: Tracks without a duration (weakens entity resolution). | 455 |
| flag | warning | missing genre information | `tracks_without_genres`: Tracks with no genre at track, album or artist level. | 1,036 |
| flag | warning | inconsistent provider identifiers | `identifier_conflicts`: Identifiers a source asserted for a track but already owned by another track (latest run of each stage). | 39 |
| pass | error | inconsistent provider identifiers | `primary_isrc_not_registered`: tracks.isrc values missing from track_external_ids. | 0 |
| pass | error | inconsistent provider identifiers | `invalid_isrc_identifiers`: ISRC identifiers not in canonical 12-character form. | 0 |
| pass | error | inconsistent provider identifiers | `invalid_musicbrainz_ids`: MusicBrainz identifiers that are not UUIDs. | 0 |
| pass | error | incorrect feature ranges | `features_out_of_range`: Unit-scale features outside [0, 1] or tempo outside 20-300 BPM. | 0 |
| flag | info | incorrect feature ranges | `suspicious_tempo`: Tempo outside the common 50-220 BPM range (often half/double-time detection). | 188 |
| pass | error | incorrect feature ranges | `genre_weights_not_normalized`: Per track/source/level genre weights that do not sum to 1. | 0 |

### Samples

**unresolved_duplicates**

```json
{"track_id": "2d3bb5c3-a788-4414-94ae-133f23403183", "candidate_track_id": "d8e20e32-09c6-47f7-838c-db1c9a324d48", "method": "metadata", "confidence": 0.7}
{"track_id": "2669f83a-b546-45a9-973a-128d124b38f4", "candidate_track_id": "ff79aad7-54cf-4680-bd52-ef56b9aafb9e", "method": "metadata", "confidence": 0.7}
{"track_id": "33307ce0-f32e-42e3-9b48-0756f0fc1a5b", "candidate_track_id": "21072bbf-5e7b-4321-b843-1a43298a5779", "method": "metadata", "confidence": 0.7}
{"track_id": "3a44c5f5-e1d4-44b7-8041-f15059366c3c", "candidate_track_id": "f37308dd-e5b6-4300-b025-d2d7cb4d14f9", "method": "metadata", "confidence": 0.7}
{"track_id": "f1b1df58-2e08-4d5b-ba55-686015322e1a", "candidate_track_id": "18e28253-d82e-4b2f-b359-c3c624d1be18", "method": "metadata", "confidence": 0.7}
```

**announced_future_releases**

```json
{"id": "2b2c4e90-32c5-445a-bfc8-baad57fb738e", "title": "hey boyyy", "release_date": "2026-12-04"}
{"id": "5ae98da5-430d-44b3-a066-0a566999fcb2", "title": "i think he’s got a girl", "release_date": "2026-12-04"}
{"id": "421b94b6-3c7c-4190-a014-0781b144e09c", "title": "The Cost to Stay", "release_date": "2027-02-05"}
{"id": "22988c4d-0eee-4eea-a1a6-ce87ec51f946", "title": "I Don't Trust Tomorrow", "release_date": "2027-03-19"}
{"id": "1db20083-cdc4-42fa-b887-8c0ba4243283", "title": "Bang Bang Bang", "release_date": "2027-01-15"}
```

**track_released_before_artist_began**

```json
{"id": "76da02ad-d4e2-41e5-88fc-c012c9a78dfd", "release_year": 2005, "begin_year": 2007}
{"id": "2e31d40e-d8f4-46fb-b314-d42deaba8355", "release_year": 1993, "begin_year": 2017}
{"id": "a1e8b41c-ee19-496e-9d96-432b5a52fa55", "release_year": 2015, "begin_year": 2017}
{"id": "84f2c840-e0c7-41fd-9fef-2224be9a752d", "release_year": 2015, "begin_year": 2017}
```

**missing_duration**

```json
{"id": "1a47d7f1-7782-4cc9-ab72-6b1bf038ce2c", "title": "LET THERE BE LIGHT"}
{"id": "f0950d85-01d1-41c5-912c-b408dfdace86", "title": "I Love It"}
{"id": "b6fc20a3-356f-4656-97dc-7852e3b5e98d", "title": "Flashing Lights"}
{"id": "f0d723c4-b17b-4094-9ce1-b7cc012711c2", "title": "All Along the Watchtower"}
{"id": "f1b1df58-2e08-4d5b-ba55-686015322e1a", "title": "Telephone"}
```

**tracks_without_genres**

```json
{"id": "582b0afe-1bde-4299-a497-1c33df0916c0", "title": "Monacillo"}
{"id": "49755219-b178-496b-8b09-1da5e2c57dcf", "title": "Freaked Out"}
{"id": "f6ddcbb5-039f-4fca-bc99-26a4a62cf234", "title": "orióN"}
{"id": "b7f1ca6d-83f6-44ab-85e5-6f1378295ac2", "title": "I'm Not Them"}
{"id": "424f9764-b006-4624-956f-bbc3fed0511b", "title": "Why"}
```

**identifier_conflicts**

```json
{"record_ref": "musicbrainz:accad857-6d36-410a-8859-3e456a08b1ac", "message": "isrc GBAYE0901205 already belongs to track 0662c608-4bed-4392-82e9-d6bedcbfa3a2"}
{"record_ref": "musicbrainz:e5dd9ecb-3fd1-4e85-9c4b-521ec87c8840", "message": "isrc USUG11904007 already belongs to track cfeb8290-993b-4f14-a9d2-65102a6162bb"}
{"record_ref": "musicbrainz:901b2b5e-b925-48ff-85a7-0053024edbbb", "message": "isrc USUM71800001 already belongs to track cfeb8290-993b-4f14-a9d2-65102a6162bb"}
{"record_ref": "musicbrainz:af62c2a8-5355-40b0-bddf-3577a77a0d38", "message": "isrc USSM19100412 already belongs to track 238da664-fea1-418d-a512-2f36c527a41c"}
{"record_ref": "musicbrainz:0b3292f6-8f0d-4160-92d3-49348029a619", "message": "isrc USSUB0200005 already belongs to track e6089259-5b0f-4079-a208-4ca42cd0df37"}
```
