# ADR-013: Initial data sources and licensing posture

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Recommendation work needs a music catalogue with metadata, content signals and real listening
interactions for time-aware evaluation. Our candidate sources have different terms:

- MusicBrainz core data is CC0, but tags and genres are CC BY-NC-SA, and its API is free only for
  non-commercial use.
- ListenBrainz, the MusicBrainz canonical dump and AcousticBrainz are CC0.
- FMA is for research, and its Echonest features have unstated terms.
- The full ListenBrainz dump is 240 GB, while daily incremental dumps are about 215 MB.

The project owner decided the posture on 2026-11-16.

## Problem

Which sources does the first catalogue use, and how do we stay able to launch commercially later?

## Alternatives considered

1. **Commercial-safe only.** Exclude CC BY-NC-SA genres/tags and research-only data. This removes
   the main content-based signal before we have our own.
2. **Research / non-commercial now, with provenance on every record.**
3. **Paid or licensed data from the start.** Premature before product validation.

## Decision

Option 2. Sources: MusicBrainz metadata and genres (via the ListenBrainz metadata API), the
MusicBrainz canonical dump (text-to-recording mapping), 14 days of ListenBrainz incremental dumps
(pseudonymised), AcousticBrainz low-level features, and FMA metadata with Echonest features
(research-only). Every record links to `data_sources`, which stores its licence and a
`usage_restriction` (`none`, `non_commercial`, `research_only`).

## Consequences

- Real interactions and rich content signals now, with full licence traceability
  (docs/DATA_SOURCES.md).
- **Before any commercial launch:** filter or replace `non_commercial` and `research_only` data
  (for example with our own genre model trained on CC0 inputs), or obtain a MetaBrainz commercial
  plan, and re-check every provider's terms.
- Listening data is personal even when public. It is pseudonymised on ingest and kept out of the
  application database.
