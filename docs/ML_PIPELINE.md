# TASTIFY — ML Pipeline and Recommendation Engine

> Derived from the approved specification [TASTIFY_v0.1.md](../TASTIFY_v0.1.md) (§7–8).
> This file is the maintained version: update it in the same pull request as the code it describes.

## 7. Data Engineering and ML Pipeline

The ML pipeline must remain independent of the web application's business logic.

### 7.1 Data Pipeline Stages

#### Stage 1: Data Ingestion

Sources:
- User interactions.
- MusicBrainz.
- ListenBrainz.
- Spotify where permitted.
- YouTube where permitted.
- Licensed or open research datasets.

#### Stage 2: Data Validation

Validate:
- Missing identifiers.
- Invalid timestamps.
- Duplicate records.
- Invalid metadata.
- Out-of-range feature values.
- Incorrect data types.

#### Stage 3: Cleaning

- Deduplicate tracks.
- Resolve artist identifiers.
- Standardize text.
- Normalize genres.
- Remove invalid records.
- Handle missing features.

#### Stage 4: Entity Resolution

Different providers may identify the same track differently.

Use:
- ISRC where available.
- Provider-specific IDs.
- Artist and track names.
- Album and release metadata.
- Duration comparison.

Never merge tracks based on title alone.

#### Stage 5: Feature Engineering

Track features:
- Genre.
- Artist.
- Album.
- Tempo, if available.
- Energy, if available.
- Mood representation.
- Audio/text embeddings where licensed.

User features:
- Genre affinity.
- Artist affinity.
- Recent listening.
- Long-term listening.
- Skip frequency.
- Replay frequency.
- Discovery preference.

#### Stage 6: Feature Storage

- PostgreSQL for structured features.
- pgvector for embeddings.
- Redis for frequently used online features.
- Object storage for permitted training artifacts.

#### Stage 7: Model Training

Train and evaluate individual recommendation approaches.

#### Stage 8: Model Evaluation

Compare against a popularity baseline and previous model versions.

#### Stage 9: Model Registration

Register:
- Model version.
- Training dataset version.
- Hyperparameters.
- Evaluation metrics.
- Feature schema.
- Training timestamp.

#### Stage 10: Model Serving

Expose recommendations through the backend recommendation service.

---

## 8. Recommendation Engine Design

### 8.1 Recommendation Approaches

#### A. Popularity Baseline

Recommend popular tracks.

Purpose:
- Cold-start fallback.
- Baseline comparison.
- General discovery.

#### B. Content-Based Filtering

Represent tracks through their metadata and available features.

Use:
- TF-IDF for textual metadata.
- Categorical encoding.
- Feature normalization.
- Embeddings.
- Cosine similarity.

#### C. Collaborative Filtering

Use user-item interactions.

Initial approaches:
- Item-item similarity.
- Implicit-feedback matrix factorization.
- ALS or equivalent techniques.

Later:
- Neural collaborative filtering.

#### D. Hybrid Recommendation

Combine content-based, collaborative and popularity signals.

Example:

```text
FinalScore =
w1(ContentScore) +
w2(CollaborativeScore) +
w3(NoveltyScore) +
w4(MoodScore) +
w5(FamiliarityScore)
```

Weights must be calibrated and normalized before combination.

#### E. Diversity Re-ranking

Use Maximal Marginal Relevance:

```text
MMR(t) = λ Rel(t,u) - (1-λ) max Sim(t,s)
```

Where:
- Rel measures user relevance.
- Sim measures similarity to already-selected tracks.
- λ controls relevance versus diversity.

### 8.2 Candidate Generation

The candidate generation stage should retrieve a larger collection than the final playlist size.

Example:
- Retrieve 300–500 candidates.
- Filter unavailable and unwanted tracks.
- Rank candidates.
- Apply diversity.
- Return the final 20–50 tracks.

These are initial experimental values, not fixed production limits.

### 8.3 Cold-Start Handling

New users:
- Onboarding preferences.
- Favourite artist selection.
- Favourite genre selection.
- Popularity-based recommendations.
- Content-based similarity.

New tracks:
- Metadata-based representation.
- Content embeddings.
- Genre and artist similarity.
- Exploration sampling.

### 8.4 User Taste Profile

Maintain two representations:

**Long-term profile**
- Stable genre preferences.
- Favourite artists.
- Historical interaction patterns.

**Short-term profile**
- Current mood preferences.
- Recent listening.
- Current session intent.
- Temporary discovery interests.

The short-term profile should not permanently overwrite long-term preferences.

### 8.5 Feedback Weighting

Initial event weights can be configurable:

| Event | Initial interpretation |
|---|---|
| Like | Strong positive |
| Save | Strong positive |
| Complete | Positive |
| Replay | Positive |
| Add to playlist | Strong positive |
| Skip very early | Negative |
| Dislike | Strong negative |

Do not treat every skip as a dislike. Users may skip for reasons unrelated to musical preference.

Weights must be tuned through experimentation.

---

## Implemented pipeline (Milestone 1)

Code lives in `ml/tastify_ml/`. It is run from `ml/` with the backend virtualenv (see DEVELOPMENT.md).
Sources and licences are listed in DATA_SOURCES.md.

```bash
python -m tastify_ml download            # raw files -> ml/data/raw/<source>/ (checksummed, resumable)
python -m tastify_ml catalogue all       # every stage below, in order
python -m tastify_ml catalogue <stage>   # a single stage
```

| Stage | Spec stage | What it does | Output |
| --- | --- | --- | --- |
| `listens` | 1 Ingestion, 2 Validation | Streams 14 daily ListenBrainz dumps in parallel. Validates each listen (user, timestamp, artist, title) and drops imports outside the dump window. Pseudonymises users (HMAC). | `processed/listens/*.parquet` |
| `mapping` | 3 Cleaning, 4 Entity resolution | Computes artist + cleaned-title matching keys (pyarrow, identical to the backend's Python rules). Streams the 7.7 GB canonical CSV, keeping only keys that occur in the listens. Maps listens to recording MBIDs, falling back to client-submitted MBIDs. Counts listeners per recording. | `processed/listen_key_mapping.parquet`, `listens_mapped/`, `recording_popularity.parquet` |
| `genres` | 3 Cleaning | Loads the MusicBrainz genre vocabulary. | `genres` |
| `catalogue` | 1, 2, 4, 7 Normalized catalogue | Seeds: the most-listened recordings (at least `CATALOGUE_MIN_LISTENERS` distinct listeners), plus the sitewide top 1000. Fetches metadata in batches of 500 (cached in `raw_records`), validates it into `SourceTrack`, and loads it through the catalogue writer (entity resolution, ADR-014). | catalogue tables |
| `interactions` | 6 Feature input | Joins mapped listens to catalogue tracks and de-duplicates them. | `processed/interactions.parquet` (user_key, track_id, listened_at) |
| `acousticbrainz` | 5 Feature extraction | Streams the rhythm and low-level feature CSVs, keeping the first submission per catalogue recording. | `track_features` (`acousticbrainz`) |
| `fma` | 1–5 | FMA genre hierarchy, the 13k tracks with Echonest features (resolved against the catalogue), and their features. | catalogue tables, `track_features` (`fma_echonest`) |
| `quality` | 2 Validation | Runs the data quality checks and writes the report. Fails if an error-severity check fails. | `docs/reports/data-quality.md`, `ml/data/reports/*.json` |

Every stage records an `ingestion_jobs` row (parameters, statistics, status) and sampled
`ingestion_errors`. Re-running a stage is idempotent: existing outputs, cached API payloads and known
provider identifiers are reused. Use `--force` to reprocess.
