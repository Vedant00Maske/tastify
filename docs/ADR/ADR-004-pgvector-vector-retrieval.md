# ADR-004: pgvector for initial vector retrieval

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Content-based and hybrid recommendation need track and user embeddings, plus nearest-neighbour
retrieval during candidate generation (spec §8.2). The target is p95 latency below 500 ms for cached
and precomputed recommendations.

## Problem

Where should embeddings live, and how should similarity search run?

## Alternatives considered

1. **Dedicated vector database** (Qdrant, Milvus, Pinecone). Built for scale and ANN performance,
   but a second datastore to operate and keep consistent with the catalogue.
2. **In-process index** (FAISS/Annoy). Very fast, but requires rebuilding and distribution, and
   cannot be filtered against relational data without extra work.
3. **pgvector in the primary PostgreSQL.**

## Decision

Use the pgvector extension in the primary database. The baseline migration enables it. Add HNSW
indexes when embedding tables are introduced and the catalogue size warrants them.

## Consequences

- Similarity search can be combined with relational filters (exclusions, languages, availability)
  in one SQL query, and stays transactionally consistent with the catalogue.
- Creating the extension needs a superuser, or a managed PostgreSQL that offers pgvector.
- Revisit when measured retrieval latency or catalogue size exceeds what pgvector handles within the
  latency target.
