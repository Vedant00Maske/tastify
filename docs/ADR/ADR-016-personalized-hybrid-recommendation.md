# ADR-016: Personalized hybrid recommendation — taste profiles, collaborative filtering, LambdaRank and diversity

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

Milestone 2 recommends from a seed (a track, an artist, a genre). Milestone 3 must understand
individual users: learn long- and short-term taste from interactions (plays, likes, skips, saves,
replays), respect what they dislike or exclude, combine content, collaborative, profile, popularity
and exploration signals, and compose diverse mixes with a user-chosen familiar/discovery balance.
It must be benchmarked on chronological data against the Milestone 2 models (the listening-profile
model was the best, NDCG@10 0.0243), reproducible, versioned, and keep FMA and licensing separate.

Constraints: SONIQUEO has no users or authentication yet (Milestone 4); the only behavioural data is
14 days of pseudonymous ListenBrainz listens, which must never enter the application database
(DATA_SOURCES.md, Privacy), and which contain plays only (no skips, likes or saves).

## Problem

Where do user data and profiles live before authentication? Which collaborative models, and how do
new SONIQUEO users (absent from training) get collaborative recommendations? How are candidate
sources combined and ranked, how is diversity applied without blindly capping every list, and how
do offline results stay faithful to what the API serves?

## Alternatives considered

1. **Offline research only.** Profiles, collaborative filtering and ranking in the ML package; no
   user data model or serving. Measurable, but the acceptance criteria (profiles that update when
   interactions arrive, user-edited preferences, cold start, served mixes) cannot be met.
2. **Serve user-user or trained user factors.** Strong offline, but it needs every research user's
   history or factors at serving time, which the privacy policy forbids, and it cannot cover users
   who joined after training.
3. **User data model now, item-level models served, shared pure logic.** SONIQUEO users, immutable
   events, preferences and derived profiles in the application database; collaborative models
   published as item-level data only (ALS track factors, item-item neighbours) with users' factors
   folded in at request time; one implementation of profiles, candidate generation, features,
   rankers and composition used by both the API and the offline evaluation.

## Decision

Option 3.

- **User data (migration `a28199fd7847`).** `users`, immutable `user_interactions` (eleven event
  types; idempotent per `client_event_id`), relational artist and genre preferences plus an
  exploration mode and a personalization opt-out, and a derived `user_taste_profiles` snapshot. The
  user endpoints take the user id in the path and are served only in local and test environments
  until Milestone 4 adds authentication.
- **Events to signals (`users/events.py`).** Configurable weights (spec §8.5): plays, completions,
  replays and playlist adds accumulate with exponential time decay; likes and saves are states
  (latest event wins) that add a bonus; only early skips (< 30 s) count as negative; a dislike is a
  strong negative and excludes the track.
- **Taste profile (`users/profile.py`).** Long-term embedding (half-life 180 days) and short-term
  embedding (half-life 3 days, 14-day window) over the content model; genre and artist affinities;
  cautious negative artists (several disliked tracks, or repeated early skips across tracks with
  no positive signal); content seeds; an exploration preference (smoothed distinct artists per
  distinct track). Declared preferences are applied on top and always win. A pure function:
  identical inputs give identical profiles; it is rebuilt on every new interaction.
- **Collaborative filtering.** The matrix holds event-weighted, time-decayed listening. ALS
  (`implicit`) on BM25-weighted confidences and BM25 item-item k-NN are served; user-user k-NN and
  BPR are benchmarks only. A user's ALS factors are solved per request from their own events and
  the published track factors and Gram matrix (identical to `implicit`'s `recalculate_user`).
- **Candidate generation.** Six independent sources (collaborative item-item, collaborative ALS,
  listening profile, content seeds, exploration of unknown similar artists, popularity in the
  user's genres) run in isolation (a failure is reported, the request still succeeds), are merged
  deterministically with their attribution kept, and filtered (heard, disliked, excluded artists,
  other versions of heard songs).
- **Ranking.** Features with recorded provenance (`features.py`). A weighted baseline (Platt-
  calibrated components, weights tuned on validation) and LightGBM LambdaRank, trained on an
  earlier period and early-stopped on validation. The served ranker is chosen by validation
  NDCG@10 (pre-declared rule) and stored as a JSON tree ensemble that the backend evaluates with
  numpy, so the API does not depend on LightGBM.
- **Composition (`diversity.py`).** Greedy MMR over the best 150 candidates with category-specific
  policies: the personal mix caps artists at 2 and balances familiar and new artists (familiar 80/20,
  balanced 50/50, explorer 20/80, or the user's own exploration preference); artist radio lets the
  seed artist fill 40% of the list; the Milestone 2 endpoints keep their rules. Negative artists
  are demoted by a fixed policy (no negative data exists to learn it from).
- **Cold start.** No history: declared artists and genres drive the profile, candidates and a
  similarity/popularity blend; nothing declared: a diverse popular mix.
- **Evaluation protocol.** Ranker-train, validation and test periods of three days each, every
  period predicted from earlier data with models retrained per period; the test period used once;
  rolling one-day windows; segments by history size, genre and item popularity; cold start;
  profile stability; reproducibility checks (docs/reports/hybrid-benchmark.md).
- **Versioning and lineage.** New model types `collaborative` and `hybrid`; artifacts (Gram
  matrix, rankers) in `model_artifacts`; every version records the signals, sources, licences and
  upstream versions it depends on. The Milestone 2 versions stay active and are snapshotted as the
  baseline.

## Consequences

Measured on 2026-11-16 (docs/reports/hybrid-benchmark.md; test period 2026-11-13 to 2026-11-16,
23,577 users, the same users as the Milestone 2 test):

- **Primary metric (pre-declared):** the LambdaRank hybrid reaches NDCG@10 0.0610 against 0.0243
  for the Milestone 2 listening-profile model (+151%, paired difference +0.0367 ± 0.0015). It is
  also significantly above its best single component, ALS (0.0578; +5.6%, ± 0.0011), and above
  the weighted hybrid (0.0584), on the test period and on each of three rolling one-day windows.
- **Ranker transfer:** a first run, with raw scores only, matched ALS on test although it led on
  validation: collaborative score scales shift with the amount of training data. Adding
  within-user percentile ranks of the score features and a more regularized configuration fixed
  it; the rank of the ALS score is now the strongest feature.
- **Collaborative filtering (validation):** ALS with 256 factors 0.0654, BM25 item-item 0.0638,
  user-user 0.0479, BPR 0.0352; the Milestone 2 profile model 0.028. The six candidate sources
  together contain 38% of the tracks users played next.
- **Trade-offs:** the for-you mix (MMR lambda 0.7, artist cap 2, balanced 50% new artists, the
  default chosen on validation) scores 0.0515: discovery and diversity cost accuracy by design.
  Familiar / balanced / explorer score 0.0569 / 0.0515 / 0.0383 with 23% / 48% / 74% new-artist
  tracks. Without the artist cap the ranking would score 0.0681.
- **Cold start:** users with 1-4 tracks 0.0383 (popularity 0.0042); onboarding answers alone
  (3 genres + 3 artists) 0.0238 against 0.0081 for popularity.
- **Profiles:** over three days the long-term embedding keeps a cosine of 0.96, the short-term one
  0.91; top-10 genres overlap 79%.
- **Licensing:** the CC0-only ranker scores 0.0608, statistically equal to the served one, so the
  non-commercial content signals are not needed for accuracy.
- **Serving:** HNSW inner-product retrieval of collaborative factors finds 99.4% of the exact top
  10 at the served ef_search; a for-you request takes about 0.45-0.55 s on the development machine.
- Reproducibility: retraining the ranker and regenerating candidates gave identical results.

- Recommendations for new SONIQUEO users need no retraining: their collaborative factors are folded
  in from their own events, and only item-level aggregates of research data are published.
- Every response names the sources and model versions behind each track and an evidence-based
  reason; a failing source degrades the mix instead of failing the request.
- The served hybrid inherits the content model's non-commercial restriction (MusicBrainz genre
  tags). A CC0-only ranker is trained, measured and stored alongside, so the commercial path is
  quantified and ready.
- Skip, like, save and dislike handling is implemented and tested but not tuned: the research data
  has none. Real usage (Milestone 8) must tune those weights and the negative-artist penalty.
- The request path runs about a dozen queries (vector searches, neighbour aggregation, facts); it is
  fast at this catalogue size but should move to a feature cache before large catalogues
  (Milestone 7).
- Revisit when SONIQUEO collects its own interactions (retrain on them, tune event weights), when
  authentication lands (Milestone 4 replaces the development user API), or if the collaborative
  signal stops beating content on fresh data.
