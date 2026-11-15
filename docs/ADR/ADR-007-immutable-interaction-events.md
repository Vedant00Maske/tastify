# ADR-007: Immutable interaction event history

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

User interactions (PLAY, COMPLETE, SKIP, LIKE, DISLIKE, SAVE, REPLAY, ADD_TO_PLAYLIST,
REMOVE_FROM_PLAYLIST) are the main training and personalisation signal. Their interpretation
(weights, the meaning of an early skip) will change through experimentation (spec §8.5).

## Problem

Should interactions be stored as mutable per-user state, or as an immutable event log?

## Alternatives considered

1. **Mutable counters or state per user–track pair.** Compact and fast to read, but history is lost,
   and features cannot be recomputed under new definitions.
2. **Aggregates only.** The same loss of information, and no audit trail.
3. **Append-only events, with aggregates derived separately.**

## Decision

Store interactions in an append-only `user_interactions` table: timestamped (UTC), linked to user,
track and session. Corrections are new events. Aggregated features are computed separately (spec
§6.4 rule 8) and never by updating events. The one exception is deletion required by privacy
requests or account deletion.

## Consequences

- Reproducible training datasets, auditability, and the ability to recompute features with new
  logic.
- Storage grows continuously, so plan time-based partitioning and a documented retention policy.
- Privacy deletion must still remove a user's events completely, including derived features.
