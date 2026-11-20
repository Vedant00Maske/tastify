# SONIQUEO ML

Offline data and machine-learning pipelines (ADR-008). They run as batch jobs, separate from the web
application, and reuse the backend's data layer: schema, entity resolution and provider clients
(ADR-012). See [docs/ML_PIPELINE.md](../docs/ML_PIPELINE.md) and
[docs/DATA_SOURCES.md](../docs/DATA_SOURCES.md).

```bash
pip install -r requirements-dev.txt        # into the backend virtualenv
python -m soniqueo_ml download              # raw public datasets -> data/raw (checksummed)
python -m soniqueo_ml catalogue all         # Milestone 1 catalogue pipeline
python -m soniqueo_ml recommend all         # Milestone 2: evaluate, publish, benchmark, report
python -m soniqueo_ml personalize all       # Milestone 3: baseline, evaluate, publish, benchmark, report
pytest                                     # needs PostgreSQL for tests marked `integration`
```

| Package | Responsibility |
| --- | --- |
| `soniqueo_ml/data/download.py`, `data/sources.py` | Dataset registry (licences), discovery and resumable, verified downloads |
| `soniqueo_ml/data/ingestion/` | Readers: ListenBrainz dumps and metadata, MusicBrainz canonical dump, AcousticBrainz, FMA |
| `soniqueo_ml/data/normalization/` | Vectorized matching keys and listen-to-recording mapping |
| `soniqueo_ml/data/quality/` | Data quality checks and reports |
| `soniqueo_ml/recommendation/` | Catalogue loading, popularity and content models, publishing, retrieval benchmark; Milestone 3: per-user signals, collaborative models (ALS, item-item, user-user, BPR), LambdaRank training and export, content assets, lineage |
| `soniqueo_ml/evaluation/` | Time-aware splits, metrics, evaluated recommenders, experiment, FMA experiment, report; Milestone 3: hybrid engine (profiles, candidates, features), hybrid experiment, segments, hybrid report |
| `soniqueo_ml/pipelines/` | Stage orchestration with job/provenance bookkeeping |

| Data folder (git-ignored) | Contents |
| --- | --- |
| `data/raw/<source>/` | Source files exactly as published |
| `data/processed/` | Derived Parquet datasets (pseudonymised listens, mappings, interactions) |
| `data/reports/` | JSON history of data quality runs |
| `data/models/` | Evaluation, publish and retrieval results (JSON) and published embeddings per version; `hybrid/` (Milestone 3 results and trained rankers); `baselines/m2/` (checksummed Milestone 2 snapshot) |

Datasets and model binaries are never committed. Their provenance is recorded in the database
(`data_sources`, `ingestion_jobs`, `raw_records`).
