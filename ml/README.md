# TASTIFY ML

Offline data and machine-learning pipelines (ADR-008). They run as batch jobs, separate from the web
application, and reuse the backend's data layer: schema, entity resolution and provider clients
(ADR-012). See [docs/ML_PIPELINE.md](../docs/ML_PIPELINE.md) and
[docs/DATA_SOURCES.md](../docs/DATA_SOURCES.md).

```bash
pip install -r requirements-dev.txt        # into the backend virtualenv
python -m tastify_ml download              # raw public datasets -> data/raw (checksummed)
python -m tastify_ml catalogue all         # Milestone 1 catalogue pipeline
pytest                                     # needs PostgreSQL for tests marked `integration`
```

| Package | Responsibility |
| --- | --- |
| `tastify_ml/data/download.py`, `data/sources.py` | Dataset registry (licences), discovery and resumable, verified downloads |
| `tastify_ml/data/ingestion/` | Readers: ListenBrainz dumps and metadata, MusicBrainz canonical dump, AcousticBrainz, FMA |
| `tastify_ml/data/normalization/` | Vectorized matching keys and listen-to-recording mapping |
| `tastify_ml/data/quality/` | Data quality checks and reports |
| `tastify_ml/pipelines/` | Stage orchestration with job/provenance bookkeeping |

| Data folder (git-ignored) | Contents |
| --- | --- |
| `data/raw/<source>/` | Source files exactly as published |
| `data/processed/` | Derived Parquet datasets (pseudonymised listens, mappings, interactions) |
| `data/reports/` | JSON history of data quality runs |

Datasets and model binaries are never committed. Their provenance is recorded in the database
(`data_sources`, `ingestion_jobs`, `raw_records`).
