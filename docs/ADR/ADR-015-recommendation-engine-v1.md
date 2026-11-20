# ADR-015: Recommendation engine V1 — popularity and content embeddings in pgvector

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Milestone 2 must let a user name a favourite track and get meaningful similar tracks, plus artist,
genre and popularity recommendations, with measurable offline evaluation. There are no SONIQUEO
users yet: the only behavioural data is 14 days of public ListenBrainz listens (6.3M listens,
39k pseudonymous users), and the only item data is the Milestone 1 catalogue (MusicBrainz genres,
AcousticBrainz audio features, release metadata). ADR-004 chose pgvector for vector retrieval and
ADR-008 offline training with online inference.

## Problem

Which models, how are they evaluated without leakage, how are they versioned and served, and how do
we make sure the offline numbers describe what the API actually returns?

## Alternatives considered

1. **Collaborative filtering now** (item-item co-occurrence or matrix factorization on listens).
   Likely more accurate on next-period listening, but it cannot recommend tracks without listening
   history, needs per-user state the app does not have yet, and is the subject of Milestone 3.
2. **Sparse exact similarity** over the full TF-IDF feature space, without a vector index. Exact,
   but it cannot use pgvector, and its cost grows with catalogue size.
3. **Popularity baselines plus a content embedding** (weighted genre TF-IDF, categorical and
   numeric features, reduced by truncated SVD to 128 dimensions), served from pgvector HNSW and
   re-ranked by shared, pure ranking rules.

## Decision

Option 3.

- **Models.** `popularity` (distinct listeners over the window, log-normalized; trending as a
  smoothed ratio of recent to earlier daily listeners, *only* when enough recent listeners and
  history exist) and `content` (track embeddings; artist embeddings as the popularity-weighted
  mean of an artist's track embeddings). Embeddings use catalogue metadata only.
- **Serving rule shared with evaluation.** `app.domains.recommendations.ranking` holds the
  candidate pool, the popularity blend `(1 - beta) * similarity + beta * popularity`, the artist
  cap, one version per song (`song_key`), and the smoothing of genre-tag votes
  (`votes / (total + 2)`, so a single user's tag cannot define a track's genre). The offline evaluation calls the same `rerank` function, so its
  metrics describe the served ranking.
- **Evaluation protocol.** Time-aware: the last 3 complete days are the test period and the 3
  days before them the validation period; each is predicted from strictly earlier interactions.
  Hyperparameters (feature weights, beta) are tuned on validation only; test is used once. The
  report (`docs/reports/model-benchmark.md`) compares against random, popularity, trending and
  genre-popularity baselines with Precision/Recall/NDCG/MAP/HitRate@K, coverage, intra-list and
  artist diversity, and novelty.
- **Versioning.** `model_versions` records each version's parameters, training window, input
  fingerprints and offline metrics; at most one version per type is active. Publishing writes a
  version's rows, activates it and deletes the serving rows of retired versions in one
  transaction, so the HNSW indexes only contain active vectors.
- **Research-only data stays out of serving.** FMA (ADR-013) is excluded from the served model and
  evaluated in a separate experiment.

## Consequences

Measured on 2026-11-16 (docs/reports/model-benchmark.md): favourite-track similarity reaches
NDCG@10 0.0210 on the held-out period, 2.2x the popularity baseline, while covering about half of the
catalogue; smoothing tag votes beat raw vote shares on validation and test; exact and HNSW retrieval
agree (tie-aware recall@10 = 1.0). Genre membership requires an affinity of at least 0.25, a product
rule that keeps popular tracks with a stray tag out of genre lists; it costs the genre baseline some
accuracy (NDCG@10 0.0129 vs 0.0140 at 0.1).

- Recommendations work for any catalogue track with metadata, including tracks nobody has played.
- Every response carries the model versions that produced it, and reasons are built only from
  recorded evidence (shared genres, similarity, listener counts).
- The SVD compression keeps about 70% of exact top-10 neighbours; this is measured in the report and
  is the price of a fixed-size vector index.
- Genre tags are CC BY-NC-SA, so the served content model inherits the non-commercial restriction.
- Changing the embedding size needs a migration (`vector(128)` is fixed in the schema).
- Revisit when SONIQUEO collects its own interactions (Milestone 3 hybrid ranking and collaborative
  filtering), when the catalogue grows past a few million tracks (HNSW parameters, memory), or if
  content similarity stops beating the popularity baseline on fresh data.
