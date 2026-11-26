# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Three overlapping audiences. None leads, and one listener often fits more than one:

- **Music diggers** hunt for new artists and genres and want to control how adventurous the
  recommendations get.
- **Mood and activity listeners** want a good playlist for right now (a mood, a task, a time of
  day) with little effort.
- **Multi-platform listeners** are split across Spotify, YouTube and ListenBrainz and want one
  taste profile they can export anywhere.

The next audience is a **small invited beta** (Milestone 8: public beta and growth). There are no
real users yet.

## Product Purpose

SONIQUEO is a personalized music discovery and playlist generation platform. It learns each
listener's taste from listening history, in-app feedback (play, complete, skip, like, dislike,
save, replay, add to and remove from playlist), declared genres, artists, moods and dislikes, and
how much the listener wants to explore. It turns that taste into recommendations and playlists.

SONIQUEO runs its own recommendation engine. Music platforms only supply metadata and user data
and receive exported playlists. The vision, from the PRD: understand not just what users listen
to, but what they enjoy, why they enjoy it and what they might discover next.

Success means recommendations visibly respond to what a listener likes, saves and skips, and
recommendation quality can be measured offline (benchmarks) and online (experiments), not just
claimed.

## Positioning

**It explains itself and does what you tell it.** SONIQUEO's own engine ranks every track, so
every pick comes with a reason. A prompt playlist shows how the prompt was read and which words
were ignored. The listener sets how familiar or exploratory the results are, plus dislikes and
exclusions, and the engine follows those settings. A streaming service's built-in
recommendations explain little and give the listener few controls. SONIQUEO makes being clear
and steerable its central promise.

## Operating Context

- **Listening happens elsewhere, for now.** SONIQUEO does not play audio yet. In-app playback is
  planned for a later release (timing and provider undecided). Until then, the persistent player
  holds a queue and "listen on" search links (currently Spotify and YouTube), and playback is
  never simulated.
- **Connected services** (Settings): Spotify (OAuth with PKCE; imports saved and recently played
  tracks; exports playlists by ISRC), YouTube (Google OAuth; exports private playlists of at
  most 50 tracks within the daily quota), ListenBrainz (token; listen import with consent;
  private playlist export), MusicBrainz (search fallback beyond the catalogue, 1 request per
  second). Services are offered only when configured. Failures with one provider don't affect
  the others.
- **First run:** register with consent, then onboarding (genres, artists, moods and exclusions,
  exploration slider), then a first mix. Prompt playlists need no listening history at all.
- **Context signals:** the browser time zone is sent with every request. The previous-hour
  session nudge is on by default (+10.5% genre predictability on unseen days). The time-of-day
  nudge is off by default because it did no better than shuffled dayparts.
- **Artwork:** Cover Art Archive covers for MusicBrainz release groups, with generated covers as
  fallback.

## Capabilities and Constraints

**Shipped (Milestones 0–7, pending review):**

- Recommendations: For You (with a context nudge and an explanation), Hidden Gems, Surprise Me,
  "Because you listened to", artist radio, eight mood mixes (genre, tempo and danceability
  recipes, regenerable), genre browsing.
- Prompt playlists (Create page): a deterministic interpreter for genres, moods, artists,
  exclusions, tempo, energy, era, popularity and familiarity, with a reason for each track.
  These are saved as playlists that can be regenerated.
- Playlists: create (empty or generated), rename, add, remove, reorder (including by keyboard),
  regenerate, suggestions, delete, export with status.
- Taste analytics: overview sentence, genre affinity, top artists, weekly trends, emerging and
  fading genres, discovery statistics. Only values that can be computed reliably are shown.
- Search (catalogue plus MusicBrainz fallback), artist and track pages, settings, data export,
  account deletion, password reset, e-mail verification.
- Loading, empty, error and offline states throughout.

**Routes:** `/home`, `/discover`, `/moods`, `/moods/[mood]`, `/create`, `/playlists`,
`/playlists/[id]`, `/taste`, `/search`, `/settings`, `/artists/[id]`, `/tracks/[id]`, auth pages,
`/onboarding`, `/privacy`, `/terms`.

**Constraints:**

- MusicBrainz tags and genre associations, the main content-based signal, are licensed CC BY-NC-SA
  3.0 (non-commercial). FMA-derived features are research-only. ListenBrainz, canonical data and
  AcousticBrainz are CC0. See `docs/DATA_SOURCES.md`.
- Spotify is in Development Mode: at most 5 allow-listed accounts can connect, and others get a
  `403`, which SONIQUEO explains to the listener. Spotify's recommendations, audio features and
  related-artists endpoints are never used.
- Each YouTube export is capped at 50 tracks by the daily API quota.
- Target: recommendation API p95 below 500 ms.
- Privacy: explicit consent before external imports, user-controlled deletion, data export, a
  retention job.

**Terminology:** mix, For You, Hidden Gems, Surprise Me, Because you listened to, mood mix,
"listen on", connected services, taste. Feedback event names: PLAY, COMPLETE, SKIP, LIKE,
DISLIKE, SAVE, REPLAY, ADD_TO_PLAYLIST, REMOVE_FROM_PLAYLIST.

**Undecided:**

- Business model. The beta is free and invite-only. Commercial plans are open, and no surface
  should imply pricing, paid tiers or ads until this is decided.
- Operator details for the privacy and terms pages, which are to be added before launch.
- In-app audio playback: planned for later; timing and provider undecided.
- Full ListenBrainz history import (background job): later.
- Browser extension (FR-017, P2): not built.

## Brand Commitments

- **Name:** SONIQUEO, written in capitals. It was renamed from TASTIFY on 2026-11-20, and the
  repository directory still uses the old name.
- **Description (site metadata):** "Personalized music discovery that learns what you enjoy and
  what you might love next."
- **Honesty commitments (from the specification and roadmap):** playback is never simulated, only
  taste values that can be computed reliably are shown, and provider limits are explained rather
  than hidden.
- **Voice (observed in shipped copy, not separately confirmed):** plain, second person, direct
  about limits. Examples: "Pick a few genres or artists so SONIQUEO has something to go on." and
  "You can delete your account at any time in Settings."

## Evidence on Hand

- Offline evaluation reports: `docs/reports/model-benchmark.md`,
  `docs/reports/hybrid-benchmark.md`, `docs/reports/context-benchmark.md`.
- Production readiness: `docs/reports/load-test.md` (20 users, about 54 requests/s, every
  endpoint's p95 below 500 ms) and `docs/reports/security-audit.md` (11 findings fixed, none
  critical).
- Catalogue quality: `docs/reports/data-quality.md`, a catalogue built from public datasets.
- **Absent, so never invent:** real users, usage numbers, testimonials, reviews, press, partner
  or customer logos, pricing. The benchmarks are offline measurements, not user outcomes. The
  PRD's non-functional targets are engineering targets, not measured guarantees.

## Product Principles

1. **Every pick can say why.** If SONIQUEO can't explain why a track is in front of the
   listener, it shouldn't be there.
2. **The listener's settings win, visibly.** Exploration level, dislikes and exclusions are
   followed, and the listener can see that they were.
3. **Honest over impressive.** Show what can be computed and backed by evidence. Don't simulate
   playback, inflate statistics or claim more than the reports show.
4. **SONIQUEO owns the taste; services are sources and destinations.** No single platform frames
   the experience.
5. **Three ways in, no gatekeeping.** Digging for new music, getting a playlist for right now,
   and moving taste across platforms are all first-class. None is hidden behind another.

## Accessibility & Inclusion

- WCAG 2.1 AA, checked with axe-core in end-to-end tests.
- Full keyboard operation, including playlist reordering, and a skip link.
- Reduced-motion support for all motion.
- No horizontal scrolling at any width from 360 to 1920 px.
