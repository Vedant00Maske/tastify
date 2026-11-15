# ADR-005: Independent recommendation engine

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Recommendation quality is the product's core value. Provider recommendation features are
unreliable as a foundation: Spotify's recommendations and audio-features endpoints are unavailable
to new apps, and every provider can change its terms and quotas. Spec principle 1: recommendation
intelligence belongs to TASTIFY.

## Problem

Should TASTIFY rely on providers' recommendation and feature APIs, or own its recommendation logic?

## Alternatives considered

1. **Wrap provider recommendation APIs.** Fast to ship, but fragile, often unavailable, not
   explainable, and not differentiating.
2. **Own ranking, but depend on provider audio features.** These features are unavailable to new
   apps, and the dependency leaks provider assumptions into the core.
3. **Own the whole pipeline**, using providers only for metadata, permitted user data and export.

## Decision

TASTIFY owns candidate generation, ranking, diversity re-ranking and explanations. Providers act
only as metadata sources, user-data sources (with consent) and playlist-export targets. No
provider-specific types or fields enter the recommendations domain.

## Consequences

- Full control over quality, explainability and evaluation against baselines (spec §8).
- More ML work: cold start is handled by onboarding, popularity and content-based methods, and data
  must come from open sources (MusicBrainz, ListenBrainz, open datasets) and our own interaction
  events.
- Provider outages degrade imports and exports, not recommendations.
