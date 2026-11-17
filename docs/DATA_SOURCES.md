# TASTIFY — Data Sources, Provenance and Licensing

> Milestone 1 deliverable. Licence facts were verified against each provider's published terms on
> 2026-11-16. Re-verify them before any public or commercial launch: terms change.

**Current posture (ADR-013): research / non-commercial.** We use every permitted research source.
Every catalogue record carries its source (`data_sources`), so non-commercial or research-only data
can be filtered out or replaced before a commercial launch. Nothing here is legal advice.

## Summary

| Source key | What we use | Licence | Usage restriction | Retrieved via |
| --- | --- | --- | --- | --- |
| `musicbrainz` | Recordings, artists, release groups, ISRCs, durations, release dates, genre tags | CC0 (core data); **CC BY-NC-SA 3.0** (tags, genre associations) | `non_commercial` | ListenBrainz `/1/metadata/recording` (batched); MusicBrainz `/ws/2/genre/all` |
| `musicbrainz_canonical` | Canonical recording per artist + title, used to link listens to recordings | CC0 | `none` | `data.metabrainz.org/pub/musicbrainz/canonical_data/` |
| `listenbrainz` | 14 daily incremental listen dumps; sitewide top recordings | CC0 | `none` | `data.metabrainz.org/pub/musicbrainz/listenbrainz/incremental/`; `/1/stats/sitewide/recordings` |
| `acousticbrainz` | Low-level audio features (tempo, danceability, onset rate, loudness) by recording MBID | CC0 | `none` | `data.metabrainz.org/pub/musicbrainz/acousticbrainz/dumps/` (final 2022-06-23 dump) |
| `fma` | 13,129 tracks with Echonest audio features, genres and hierarchy | CC BY 4.0 (metadata); Echonest-derived values: **licence unstated** | `research_only` | `os.unil.cloud.switch.ch/fma/fma_metadata.zip` (SHA-1 from the FMA README) |

Commercial-use notes:

- **MusicBrainz:** the web service is free for non-commercial use only; commercial users are
  directed to a paid MetaBrainz plan. The data dumps allow commercial use, but financial support is
  "strongly urged". Tags and genre associations are CC BY-NC-SA, which is the main obstacle, since
  they are our main content-based signal.
- **ListenBrainz / canonical data / AcousticBrainz:** CC0. MetaBrainz asks commercial users to
  support them financially. The social contract forbids charging for the data itself.
- **FMA:** described as "meant for research purposes". The audio licence varies per track and is
  not used (no audio was downloaded). Echonest features originate from a commercial API (now
  Spotify), and their redistribution terms are not stated, so treat them as research-only.

## Milestone 1 sample catalogue (built 2026-11-16)

Full numbers and checks are in [reports/data-quality.md](reports/data-quality.md).

| Step | Result |
| --- | --- |
| Listen dumps (2026-11-03 to 2026-11-16) | 68.0M lines. 20.3M listens kept; 47.8M bulk-imported history outside the window dropped |
| Text → recording mapping | 3.73M distinct artist/title keys, 1.93M matched. 72.7% of listens mapped by text, 1.3% by client-submitted MBID |
| Catalogue seeds | 30,099 recordings (top by distinct listeners with at least 3 listeners, plus the sitewide top 1000) |
| Catalogue | 42,952 tracks (29,848 MusicBrainz, 13,104 FMA), 8,865 artists, 14,252 albums, 2,296 genres |
| Entity resolution | 130 MusicBrainz recordings linked by ISRC or metadata; 24 FMA-internal duplicates linked; 100 possible duplicates queued for review; 39 identifier conflicts reported |
| Audio features | 18,727 tracks (AcousticBrainz) + 13,104 (FMA Echonest) = 74% of tracks |
| Interactions for evaluation | 6.34M de-duplicated listens on catalogue tracks, by 39,013 pseudonymous users |

Known limitations:

- **FMA and MusicBrainz barely overlap.** FMA is independent Creative Commons music; the MusicBrainz
  seeds are what ListenBrainz users actually play. No FMA track met the linking rules against a
  MusicBrainz track. The cross-source linking path is covered by tests and will matter for
  Spotify/YouTube imports (Milestone 5).
- 27% of listens could not be mapped to a recording (misspellings, obscure or unreleased tracks).
- AcousticBrainz stopped in 2022, so recent releases have no AcousticBrainz features.
- Search over "artist title" takes about 0.3 s at this size, because the concatenated expression is
  not indexed. Revisit with a dedicated search column or index before the catalogue grows.

## Use in recommendation models (Milestone 2)

The served models (ADR-015) are trained only on sources whose `usage_restriction` is not
`research_only`: MusicBrainz tracks with their genres and AcousticBrainz features, and ListenBrainz
popularity. FMA is used only in a separate offline experiment (audio features vs FMA's genre
labels), reported in [reports/model-benchmark.md](reports/model-benchmark.md). Because MusicBrainz
genre tags are CC BY-NC-SA and are the content model's main signal, the served content model is
non-commercial too.

## Use in recommendation models (Milestone 3)

Every published model version records its **lineage** in `model_versions.training_data.lineage`:
the signals it uses, their source, licence and usage restriction, the upstream model versions, and
the resulting restriction (`tastify_ml/recommendation/lineage.py`, ADR-016). MusicBrainz is split
by component, because its core data (recording and artist identities, titles, release metadata) is
CC0 while tags and genre associations are CC BY-NC-SA.

| Model | Signals | Usage restriction |
| --- | --- | --- |
| `popularity` | ListenBrainz listens, canonical listen-to-recording mapping | none |
| `collaborative` (ALS factors, item-item neighbours) | the above, plus MusicBrainz core data (track identities) | none |
| `content` | MusicBrainz core data, **MusicBrainz genre tags** | non-commercial |
| `hybrid` (served ranker) | all of the above, plus TASTIFY users' own interactions | **non-commercial** |
| `hybrid` CC0 ranker (artifact `ranker_cc0`, not served) | collaborative, popularity, user interactions only | none |

Each ranking feature also records its restriction (`app/domains/recommendations/features.py`), so a
commercially usable ranker can be retrained without the content signals; the benchmark report
measures what that costs. FMA stays out of every served model. Research listens are used only to
train item-level models: no research user's history, profile or factors is published.

## Provenance in the database

| Table | Provenance it records |
| --- | --- |
| `data_sources` | Licence, licence URL, usage restriction, attribution and notes for each source |
| `ingestion_jobs` | Each pipeline stage run: source, parameters (files, window, sizes), statistics, status |
| `ingestion_errors` | Rejected or flagged records with stage, code, reference and message (sampled, 200 per code) |
| `raw_records` | Every API response exactly as received, with its SHA-256, so the catalogue can be rebuilt offline |
| `tracks` / `artists` / `albums` `.source_id` | The source that created the canonical record |
| `*_external_ids.source_id`, `.match_method`, `.confidence` | Who asserted each identifier, and how it was matched |
| `track_genres.source_id` / `.level` | Where each genre came from and at what level (recording or album) |
| `track_features.feature_source` / `.feature_version` | The source and version of every audio feature row |

Raw files are kept unmodified in `ml/data/raw/<source>/` and verified against published checksums
(SHA-256, or SHA-1 for FMA) before use. They are git-ignored.

## Privacy (ListenBrainz listens)

Listens are public CC0 data, but user names identify real people. On ingest:

1. User names are replaced by `HMAC-SHA256(LISTENS_PSEUDONYM_KEY, user_name)`, truncated to 20 hex
   characters. The key lives only in `.env`. Raw user names are never written to disk or the
   database.
2. Only the fields needed for recommendation research are kept: pseudonymous user key, timestamp,
   artist, track and release names, duration, and any client-submitted recording MBID.
3. Listens stay in git-ignored Parquet files (`ml/data/processed/`). They never enter the
   application database, where `users` and `user_interactions` are reserved for TASTIFY's own users
   (spec §12.4).
4. Bulk imports of old listening history are dropped: only listens whose own timestamp falls inside
   the dump window are kept.

To delete everything derived from listens, remove `ml/data/processed/listens*`,
`ml/data/processed/interactions.parquet` and the raw dumps.

## Audio feature mapping

`track_features` uses one set of columns for every source. Scales differ, so each source's values
are mapped as follows and versioned:

| Column | AcousticBrainz (`acousticbrainz-lowlevel-2022-06-23`) | FMA Echonest (`echonest-fma-2017`) |
| --- | --- | --- |
| `tempo` (BPM) | `rhythm.bpm` (kept if 20–300) | `tempo` |
| `danceability` [0, 1] | `rhythm.danceability / 3`, clipped (Essentia DFA scale ≈ 0–3) | `danceability` |
| `energy` [0, 1] | — | `energy` |
| `valence` [0, 1] | — | `valence` |
| `acousticness` [0, 1] | — | `acousticness` |
| `instrumentalness` [0, 1] | — | `instrumentalness` |
| `loudness` [0, 1] | `lowlevel.average_loudness` | — |
| `onset_rate` (per second) | `rhythm.onset_rate` | — |

Features from different sources are **not interchangeable** (for example Essentia vs Echonest
danceability). Models must use `feature_source` as part of the feature definition.

## Entity resolution policy

Implemented in `backend/app/domains/catalogue/resolution.py` and documented in ADR-014.

| Evidence | Decision |
| --- | --- |
| Same provider identifier already in the catalogue | Update that track (idempotent re-runs) |
| Shared ISRC, durations within 10 s, artists similar (≥ 0.5) | Link (`isrc`, confidence 0.99) |
| Shared ISRC but durations or artists disagree | Separate track and a review record |
| Same cleaned title and artist, durations within 3 s | Link (`metadata`, 0.90, or 0.95 with the same album) |
| Same title and artist, durations unknown | Separate track and a review record |
| Near-identical title and artist (similarity ≥ 0.9), durations within 3 s | Separate track and a review record |
| Same title and artist, durations more than 3 s apart | Different recording (live, edit, remix) |
| Title alone | Never linked |
| Several tracks qualify for linking | Ambiguous: none linked, all recorded for review |

"Cleaned title" removes featuring credits and remaster notes only. Live, remix, acoustic and edit
markers are kept, because they denote different recordings.

## Refreshing the data

```bash
cd ml
python -m tastify_ml download          # newest dumps, verified against published checksums
python -m tastify_ml catalogue all     # rebuild; every stage is idempotent
```

Respect provider limits. The pipeline sends at most one request per second to MusicBrainz and
ListenBrainz, identifies itself with `METABRAINZ_USER_AGENT`, and backs off on 429/503. Downloads
use three parallel streams.
