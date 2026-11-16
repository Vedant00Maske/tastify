# ADR-014: Conservative, explainable entity resolution

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

The same recording reaches us from several providers with different identifiers, and later from
Spotify and YouTube too. Wrongly merging two recordings corrupts interaction data and
recommendations, and is hard to undo. Missing a merge only leaves a duplicate, which is visible and
reversible. The spec says: never merge on title alone; ambiguous matches stay unresolved until
verified.

## Problem

How do we decide that two source records are the same canonical track?

## Alternatives considered

1. **A learned matcher** (for example a classifier on similarity features). Potentially higher
   recall, but it needs labelled pairs we don't have, and its decisions are harder to explain.
2. **A weighted score with one threshold.** Simple, but a single number hides why a match
   happened, and tuning it trades errors invisibly.
3. **Explicit rules ordered by evidence strength, with a review queue for anything uncertain.**

## Decision

Option 3, implemented as pure functions in `app.domains.catalogue.resolution`:

- Identifier evidence (shared ISRC) links, unless duration or artist contradict it.
- Metadata evidence links only when the cleaned title and the artist match exactly and durations
  agree within 3 s.
- Weaker or contradictory evidence creates a separate track plus an `entity_match_candidates` row
  with the evidence signals.
- Several qualifying candidates are treated as ambiguous: none are linked.

Every link records its `match_method` and `confidence`. Candidate lookup uses an indexed
artist/title matching key and ISRCs. The exact table of rules is in docs/DATA_SOURCES.md.

## Consequences

- Merges are explainable and auditable. False merges are rare by design.
- Some true duplicates remain separate until reviewed. The data-quality report tracks pending
  reviews and same-key duplicates.
- Labelled review outcomes (accepted/rejected) will become training data for a learned matcher
  later, if recall becomes a problem.
