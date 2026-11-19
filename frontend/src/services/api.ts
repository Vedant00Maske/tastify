/** Typed operations of the TASTIFY API (docs/API_SPEC.md), one function per endpoint. */
import {
  ArtistDetailSchema,
  AuthorizeSchema,
  ImportRunSchema,
  ArtistSearchSchema,
  BecauseYouListenedSchema,
  CustomResponseSchema,
  FeedbackStatesSchema,
  GenreListSchema,
  InteractionHistorySchema,
  InteractionsRecordedSchema,
  MeSchema,
  MoodListSchema,
  MoodMixSchema,
  PersonalizedResponseSchema,
  PlaylistDetailSchema,
  PlaylistExportListSchema,
  PlaylistExportSchema,
  PlaylistListSchema,
  PreferencesSchema,
  ProviderListSchema,
  RecordingSearchSchema,
  RecommendationResponseSchema,
  TasteAnalyticsSchema,
  TasteProfileSchema,
  TrackDetailSchema,
  TrackSearchSchema,
  type CustomRequest,
  type EventType,
  type ExplorationMode,
  type Generator,
  type PreferencesUpdate,
} from "@/types/api";

import { apiFetch, withQuery } from "./api-client";

// --- auth and account ------------------------------------------------------------------------

export const auth = {
  register: (body: {
    email: string;
    password: string;
    display_name?: string;
    accept_terms: boolean;
  }) => apiFetch("/auth/register", { method: "POST", body, schema: MeSchema }),
  login: (body: { email: string; password: string }) =>
    apiFetch("/auth/login", { method: "POST", body, schema: MeSchema }),
  logout: () => apiFetch<void>("/auth/logout", { method: "POST" }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    apiFetch<void>("/auth/password", { method: "POST", body }),
};

export const account = {
  me: () => apiFetch("/users/me", { schema: MeSchema }),
  update: (body: {
    display_name?: string | null;
    onboarding_completed?: boolean;
  }) => apiFetch("/users/me", { method: "PATCH", body, schema: MeSchema }),
  remove: (password: string) =>
    apiFetch<void>("/users/me", { method: "DELETE", body: { password } }),
  preferences: () =>
    apiFetch("/users/me/preferences", { schema: PreferencesSchema }),
  updatePreferences: (body: PreferencesUpdate) =>
    apiFetch("/users/me/preferences", {
      method: "PUT",
      body,
      schema: PreferencesSchema,
    }),
  tasteProfile: () =>
    apiFetch("/users/me/taste-profile", { schema: TasteProfileSchema }),
  taste: () => apiFetch("/users/me/taste", { schema: TasteAnalyticsSchema }),
  exportUrl: "/users/me/export",
};

// --- catalogue -------------------------------------------------------------------------------

export const catalogue = {
  searchTracks: (q: string, limit = 20) =>
    apiFetch(withQuery("/tracks/search", { q, limit }), {
      schema: TrackSearchSchema,
    }),
  searchArtists: (q: string, limit = 20) =>
    apiFetch(withQuery("/artists/search", { q, limit }), {
      schema: ArtistSearchSchema,
    }),
  track: (id: string) =>
    apiFetch(`/tracks/${id}`, { schema: TrackDetailSchema }),
  artist: (id: string) =>
    apiFetch(`/artists/${id}`, { schema: ArtistDetailSchema }),
  genres: (limit = 60) =>
    apiFetch(withQuery("/genres", { limit }), { schema: GenreListSchema }),
};

// --- recommendations -------------------------------------------------------------------------

export const recommendations = {
  forYou: (limit = 25, exploration?: ExplorationMode) =>
    apiFetch(withQuery("/recommendations/for-you", { limit, exploration }), {
      schema: PersonalizedResponseSchema,
    }),
  hiddenGems: (limit = 20) =>
    apiFetch(withQuery("/recommendations/hidden-gems", { limit }), {
      schema: PersonalizedResponseSchema,
    }),
  surprise: () =>
    apiFetch("/recommendations/surprise", {
      schema: PersonalizedResponseSchema,
    }),
  becauseYouListened: (seeds = 2, limit = 10) =>
    apiFetch(
      withQuery("/recommendations/because-you-listened", { seeds, limit }),
      {
        schema: BecauseYouListenedSchema,
      },
    ),
  moods: () => apiFetch("/recommendations/moods", { schema: MoodListSchema }),
  mood: (mood: string, limit = 25, exclude: string[] = []) =>
    apiFetch(
      withQuery(`/recommendations/mood/${encodeURIComponent(mood)}`, {
        limit,
        exclude,
      }),
      {
        schema: MoodMixSchema,
      },
    ),
  similar: (trackId: string, limit = 20) =>
    apiFetch(withQuery(`/recommendations/similar/${trackId}`, { limit }), {
      schema: RecommendationResponseSchema,
    }),
  similarArtists: (artistId: string, limit = 20) =>
    apiFetch(withQuery(`/recommendations/artist/${artistId}`, { limit }), {
      schema: RecommendationResponseSchema,
    }),
  artistRadio: (artistId: string, limit = 25) =>
    apiFetch(
      withQuery(`/recommendations/artist-radio/${artistId}`, { limit }),
      {
        schema: RecommendationResponseSchema,
      },
    ),
  genre: (genre: string, limit = 20) =>
    apiFetch(
      withQuery(`/recommendations/genre/${encodeURIComponent(genre)}`, {
        limit,
      }),
      {
        schema: RecommendationResponseSchema,
      },
    ),
  custom: (body: CustomRequest) =>
    apiFetch("/recommendations/custom", {
      method: "POST",
      body,
      schema: CustomResponseSchema,
    }),
  popular: (limit = 20, kind: "all_time" | "trending" = "all_time") =>
    apiFetch(withQuery("/recommendations/popular", { limit, kind }), {
      schema: RecommendationResponseSchema,
    }),
};

// --- interactions ----------------------------------------------------------------------------

export interface FeedbackEvent {
  track_id: string;
  event_type: EventType;
  request_id?: string;
  position_ms?: number;
  client_event_id?: string;
}

export const interactions = {
  record: (events: FeedbackEvent[], source = "app") =>
    apiFetch("/interactions", {
      method: "POST",
      body: { events, source },
      schema: InteractionsRecordedSchema,
    }),
  history: (
    options: { limit?: number; before?: string; eventTypes?: EventType[] } = {},
  ) =>
    apiFetch(
      withQuery("/interactions/history", {
        limit: options.limit ?? 50,
        before: options.before,
        event_type: options.eventTypes,
      }),
      { schema: InteractionHistorySchema },
    ),
  state: (trackIds: string[]) =>
    apiFetch(withQuery("/interactions/state", { track_id: trackIds }), {
      schema: FeedbackStatesSchema,
    }),
};

// --- playlists -------------------------------------------------------------------------------

export const playlists = {
  list: () => apiFetch("/playlists", { schema: PlaylistListSchema }),
  get: (id: string) =>
    apiFetch(`/playlists/${id}`, { schema: PlaylistDetailSchema }),
  create: (body: {
    name: string;
    description?: string | null;
    track_ids?: string[];
    generator?: Generator;
  }) =>
    apiFetch("/playlists", {
      method: "POST",
      body,
      schema: PlaylistDetailSchema,
    }),
  update: (id: string, body: { name?: string; description?: string | null }) =>
    apiFetch(`/playlists/${id}`, {
      method: "PATCH",
      body,
      schema: PlaylistDetailSchema,
    }),
  remove: (id: string) =>
    apiFetch<void>(`/playlists/${id}`, { method: "DELETE" }),
  addTracks: (id: string, trackIds: string[]) =>
    apiFetch(`/playlists/${id}/tracks`, {
      method: "POST",
      body: { track_ids: trackIds },
      schema: PlaylistDetailSchema,
    }),
  removeTrack: (id: string, trackId: string) =>
    apiFetch(`/playlists/${id}/tracks/${trackId}`, {
      method: "DELETE",
      schema: PlaylistDetailSchema,
    }),
  reorder: (id: string, trackIds: string[]) =>
    apiFetch(`/playlists/${id}/tracks/order`, {
      method: "PUT",
      body: { track_ids: trackIds },
      schema: PlaylistDetailSchema,
    }),
  regenerate: (id: string) =>
    apiFetch(`/playlists/${id}/regenerate`, {
      method: "POST",
      schema: PlaylistDetailSchema,
    }),
  suggestions: (id: string, limit = 10) =>
    apiFetch(withQuery(`/playlists/${id}/suggestions`, { limit }), {
      schema: RecommendationResponseSchema,
    }),
};

// --- integrations ----------------------------------------------------------------------------

export const integrations = {
  list: () => apiFetch("/integrations", { schema: ProviderListSchema }),
  connectToken: (provider: string, token: string) =>
    apiFetch(`/integrations/${provider}/connect`, {
      method: "POST",
      body: { token },
      schema: ProviderListSchema,
    }),
  authorize: (provider: string) =>
    apiFetch(`/integrations/${provider}/authorize`, {
      schema: AuthorizeSchema,
    }),
  disconnect: (provider: string, deleteImported: boolean) =>
    apiFetch<void>(
      withQuery(`/integrations/${provider}`, {
        delete_imported: deleteImported,
      }),
      { method: "DELETE" },
    ),
  importHistory: (provider: string) =>
    apiFetch(`/integrations/${provider}/import`, {
      method: "POST",
      body: { consent: true },
      schema: ImportRunSchema,
    }),
  searchMusicBrainz: (q: string) =>
    apiFetch(withQuery("/integrations/musicbrainz/search", { q, limit: 8 }), {
      schema: RecordingSearchSchema,
    }),
  exports: (playlistId: string) =>
    apiFetch(`/playlists/${playlistId}/exports`, {
      schema: PlaylistExportListSchema,
    }),
  exportPlaylist: (playlistId: string, provider: string) =>
    apiFetch(`/playlists/${playlistId}/export`, {
      method: "POST",
      body: { provider },
      schema: PlaylistExportSchema,
    }),
};
