# TASTIFY ML

Offline data and machine-learning pipelines (ADR-008). The code runs as batch jobs, independently of
the web application's business logic, and hands registered models and precomputed artifacts to the
backend for inference. Implementation starts in Milestone 1 (data foundation) and Milestone 2
(recommendation v1). See [docs/ML_PIPELINE.md](../docs/ML_PIPELINE.md).

| Folder                | Responsibility                                                                         |
| --------------------- | -------------------------------------------------------------------------------------- |
| `data/ingestion/`     | Pull from interactions, MusicBrainz, ListenBrainz and permitted provider/open datasets |
| `data/validation/`    | Schema, identifier, timestamp, duplicate and range checks                              |
| `data/cleaning/`      | Deduplication, text standardisation, invalid-record removal                            |
| `data/normalization/` | Genre normalisation, artist/track entity resolution (ISRC, MBID, never title alone)    |
| `features/`           | Track and user feature engineering                                                     |
| `embeddings/`         | Track/user embedding generation (stored in pgvector)                                   |
| `models/`             | `popularity/` baseline, `content_based/`, `collaborative/`, `hybrid/`                  |
| `ranking/`            | Scoring and diversity re-ranking experiments                                           |
| `evaluation/`         | Precision@K, Recall@K, NDCG@K, MAP@K, coverage, diversity, novelty vs. baseline        |
| `experiments/`        | Experiment configs and notebooks (tracked with MLflow)                                 |
| `inference/`          | Packaging of models and artifacts consumed by the backend                              |

Datasets and model binaries are not committed to git (see `.gitignore`). Record their provenance
and versions per the Definition of Done for ML features.
