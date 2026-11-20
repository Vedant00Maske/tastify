# ADR-019: Advanced recommendation intelligence — evidence-based context, prompt playlists and online experiments

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Milestone 6 asks for context-aware ranking, cold-start and quality improvements, natural-language
playlist generation (spec §9 `POST /recommendations/custom`, FR-016), experimentation (spec §8.5:
"weights must be tuned through experimentation") and optimization. The spec also requires that
"scores and reasons must be based on actual model outputs and recorded evidence" and keeps a
`RecommendationLog` entity (§6.2) that had not been built.

Two context signals were candidates: time of day (dayparts) and the current session (spec §8.4
"current session intent"). Both can be checked offline on the research listens, which have UTC
timestamps but no time zones.

## Problem

Which context signals actually predict listening, and how strongly may they move a ranking? How
does a free-text prompt become a playlist whose every track can be justified? How are changes
evaluated online without a second deployment, and how does that stay privacy-compatible? Where
is latency going?

## Alternatives considered

1. **Ship time-of-day and session context unconditionally.** Popular in products, but untested
   here; a wrong prior would degrade every mix.
2. **A large language model for prompts.** Flexible language, but it adds an external dependency
   and cost, and its choices cannot be traced to catalogue evidence (§9).
3. **Measure first, then ship what the evidence supports behind an experiment; read prompts with
   a deterministic interpreter over the catalogue's own vocabulary; log every recommendation so
   variants can be compared on attributed feedback.**

## Decision

Option 3.

**Context, measured offline** (`python -m soniqueo_ml context`,
[context-benchmark.md](../reports/context-benchmark.md); method in
`ml/soniqueo_ml/evaluation/context_experiment.py`, sharing `app/domains/recommendations/context.py`
with the API):

- *Time of day:* research users' UTC offsets are inferred from their quietest four hours (7,448 of
  38,851 users qualify). A daypart genre model is **not** better than the overall profile on
  unseen days (−0.36% cross-entropy) and no better than shuffled dayparts. It stays **off**
  (`DEFAULT_DAYPART_WEIGHT = 0`); an experiment can switch it on with the validated shrinkage
  (K = 100).
- *Session:* the previous hour's listening predicts the next listen's genres **10.5% better**
  than the overall profile, while the same hour one day earlier does 4.8% worse (so the gain is
  the session, not recent taste in general). It is **on**: a genre-level session fit (shrinkage
  K = 2, at least 2 session events) nudges for-you relevance by `session_weight = 0.1`, mentioned
  in the reason when it mattered. The browser sends its IANA time zone (`X-Timezone`) so daypart
  experiments use local time.

**Prompt playlists** (`POST /recommendations/custom`): `prompts.parse` reads catalogue genres
(longest phrase first), the eight moods and their everyday words, artists after cues ("like",
"similar to", "by"), exclusions ("no", "without"), tempo, energy, era, popularity and
familiarity. Artists are resolved by exact normalized name, else trigram similarity ≥ 0.55.
Candidates are genre/mood tag members and the named artists' and their nearest artists'
tracks; constraints filter; the score combines genre fit (rewarding tracks that bring every
requested genre), artist similarity, taste similarity (signed in) and popularity tempered by
the requested exploration; MMR composes the list. The response returns the interpretation,
including ignored words; a prompt with nothing recognisable is a `422` that lists them.
Prompts can be saved as regenerable playlists (collection `custom`).

**Logging and experiments.** Every personalized response (for you, hidden gems, surprise, moods
and prompts when signed in) is logged: `recommendation_requests` (category, strategy, model
versions, experiment and variant, context, latency) and per-item `recommendation_logs` (§6.2).
Feedback can carry the `request_id`. Experiments live in `experiments` (surface, weighted
variants with parameters); users are assigned by hashing (experiment, user), so assignment is
stable and stores nothing. The report compares positive (like, save, playlist add) and negative
(dislike) feedback per shown item with Wilson intervals and a two-proportion z-test, and refuses a
verdict below 1,000 items per variant. Managed with `python -m soniqueo_ml experiments …`.
Logs are personal data: included in the data export, deleted with the account, pruned after
`RECOMMENDATION_LOG_RETENTION_DAYS` (90).

**Optimization**, from profiling one for-you request (773 ms in process with the session
nudge): genre popularity rankings are cached per published popularity version (not personal,
immutable), track genre profiles per content version, and only the 250 best candidates are
scored for context (the composer considers 150; a 0.1 nudge cannot lift anything from further
down). Result: about 530 ms (−30%), identical rankings.

## Consequences

- Context that the data does not support is not shipped; the online experiment decides whether
  the session nudge's weight should change.
- Prompt understanding is limited to the catalogue's vocabulary and fixed phrases; unrecognised
  words are shown, not guessed. A language-model front end could later produce the same
  structured intent without changing ranking or evidence.
- Every recommendation adds rows; retention and pruning keep the tables bounded.
- Caches are per process and keyed by immutable model versions, so they never serve stale data;
  memory is bounded (256 popularity rankings, 50,000 genre profiles).
