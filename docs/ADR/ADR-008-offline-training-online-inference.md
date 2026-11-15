# ADR-008: Separate offline training and online inference

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Model training is batch-oriented, resource-heavy and experimental. Serving must be fast (p95 below
500 ms for precomputed recommendations) and reliable. The spec requires the ML pipeline to stay
independent of web business logic (§7).

## Problem

Where do training and inference run, and how do models reach production?

## Alternatives considered

1. **Train inside the web application.** Simple wiring, but training load hurts request latency, and
   the coupling makes experiments risky.
2. **A continuously running online-learning service.** Fresh models, but much more complexity than
   the current data volume justifies.
3. **Offline training jobs, with serving in the backend from registered artifacts.**

## Decision

The `ml/` package holds ingestion, validation, feature engineering, training and evaluation. It runs
as batch jobs, not as a long-running service. Trained models are registered with their version,
dataset version, hyperparameters, metrics and feature schema (MLflow). The backend loads registered
artifacts and precomputed embeddings and candidates for inference, and logs `model_version` with
every recommendation.

## Consequences

- Training never affects API latency, and experiments are reproducible and comparable.
- An artifact hand-off is needed (registry and object storage), and feature definitions must stay
  consistent between offline training and online serving.
- Revisit if freshness requirements demand near-real-time updates beyond the short-term profile.
