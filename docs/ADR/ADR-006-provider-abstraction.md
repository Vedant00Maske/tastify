# ADR-006: Provider abstraction for music integrations

- **Status:** Accepted
- **Date:** 2026-11-16

## Context

SONIQUEO integrates with Spotify, YouTube, ListenBrainz and MusicBrainz. They differ in
authentication, capabilities, quotas, identifiers and failure modes. Not every provider supports
every operation (spec §10.1).

## Problem

How do business services use providers without coupling to any one of them?

## Alternatives considered

1. **Call provider SDKs and APIs directly from domain services.** Quick at first, but provider
   details spread everywhere, and testing and replacing providers becomes hard.
2. **One generic HTTP client with per-provider configuration.** This hides real differences in
   auth and capabilities behind leaky configuration.
3. **A common interface with per-provider adapters and capability detection.**

## Decision

Define a `MusicProvider` interface (`authorize`, `refresh_token`, `search_tracks`,
`get_track_metadata`, `get_user_library`, `export_playlist`, `disconnect`) and give each provider an
adapter in the integrations domain. Adapters declare their capabilities, normalise data into the
internal catalogue, and own provider-specific rate limiting, retries and error mapping.

## Consequences

- Provider failures are isolated, and adapters are testable with fakes and contract tests.
- New providers are added without touching recommendation or playlist logic.
- The capability matrix and the normalisation rules must be maintained and documented in
  INTEGRATIONS.md.
