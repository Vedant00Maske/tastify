/**
 * API contracts. Zod schemas mirror the backend's Pydantic models (the backend schemas.py modules);
 * every response is validated at runtime by the API client, and the TypeScript types are inferred
 * from the same schemas, so the two cannot drift apart silently.
 */
import { z } from "zod";

// --- health (backend/app/schemas/health.py) -------------------------------------------------

export type CheckStatus = "ok" | "unavailable";

export interface HealthResponse {
  status: "ok";
  version: string;
}

export interface ReadinessResponse {
  status: CheckStatus;
  checks: Record<string, CheckStatus>;
}

// --- auth and account ------------------------------------------------------------------------

export const MeSchema = z.object({
  id: z.uuid(),
  email: z.string(),
  display_name: z.string().nullable(),
  created_at: z.string(),
  onboarding_completed: z.boolean(),
  email_verified: z.boolean(),
});
export type Me = z.infer<typeof MeSchema>;

// --- catalogue -------------------------------------------------------------------------------

export const TrackSummarySchema = z.object({
  id: z.uuid(),
  title: z.string(),
  artist: z.string(),
  duration_ms: z.number().nullable(),
  release_year: z.number().nullable(),
  artist_id: z.uuid().nullable().optional(),
  album_title: z.string().nullable().optional(),
  artwork_url: z.string().nullable().optional(),
});
export type TrackSummary = z.infer<typeof TrackSummarySchema>;

export const TrackDetailSchema = TrackSummarySchema.extend({
  isrc: z.string().nullable(),
  credits: z.array(
    z.object({
      artist_id: z.uuid(),
      name: z.string(),
      join_phrase: z.string(),
    }),
  ),
  album: z
    .object({
      id: z.uuid(),
      title: z.string(),
      album_type: z.string().nullable(),
      release_year: z.number().nullable(),
    })
    .nullable(),
  genres: z.array(
    z.object({
      name: z.string(),
      weight: z.number(),
      level: z.string(),
      source: z.string(),
    }),
  ),
});
export type TrackDetail = z.infer<typeof TrackDetailSchema>;

export const ArtistSummarySchema = z.object({
  id: z.uuid(),
  name: z.string(),
  area: z.string().nullable(),
  genres: z.array(z.string()),
  track_count: z.number(),
  artwork_url: z.string().nullable(),
});
export type ArtistSummary = z.infer<typeof ArtistSummarySchema>;

export const ArtistDetailSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  artist_type: z.string().nullable(),
  area: z.string().nullable(),
  begin_year: z.number().nullable(),
  genres: z.array(z.object({ name: z.string(), weight: z.number() })),
  track_count: z.number(),
});
export type ArtistDetail = z.infer<typeof ArtistDetailSchema>;

export const TrackSearchSchema = z.object({
  query: z.string(),
  results: z.array(TrackSummarySchema),
});
export const ArtistSearchSchema = z.object({
  query: z.string(),
  results: z.array(ArtistSummarySchema),
});
export const GenreListSchema = z.object({
  genres: z.array(z.object({ name: z.string(), tracks: z.number() })),
});
export type Genre = z.infer<typeof GenreListSchema>["genres"][number];

// --- recommendations -------------------------------------------------------------------------

export const SourceSchema = z.object({
  source: z.string(),
  retrieval_score: z.number(),
  rank: z.number(),
  model_version: z.string().nullable(),
});

export const RecommendationItemSchema = z.object({
  track_id: z.uuid(),
  title: z.string(),
  artist: z.string(),
  artist_id: z.uuid().nullable().optional(),
  album: z.string().nullable().optional(),
  artwork_url: z.string().nullable().optional(),
  score: z.number(),
  reason: z.string(),
  discovery: z.boolean().optional(),
  sources: z.array(SourceSchema).optional(),
});
export type RecommendationItem = z.infer<typeof RecommendationItemSchema>;

export const StrategySchema = z.enum([
  "similar_tracks",
  "similar_artists",
  "genre",
  "popular",
  "trending",
  "personalized",
  "cold_start",
  "artist_radio",
  "mood",
  "hidden_gems",
  "because_you_listened",
  "surprise",
  "custom",
]);

export const RecommendationResponseSchema = z.object({
  request_id: z.uuid(),
  model_version: z.string(),
  model_versions: z.record(z.string(), z.string()),
  strategy: StrategySchema,
  recommendations: z.array(RecommendationItemSchema),
});
export type RecommendationResponse = z.infer<
  typeof RecommendationResponseSchema
>;

export const PersonalizedResponseSchema = RecommendationResponseSchema.extend({
  user_id: z.uuid().nullable(),
  profile_version: z.string().nullable(),
  ranker: z.string(),
  composition: z.object({
    familiar: z.number(),
    discovery: z.number(),
    discovery_target: z.number().nullable(),
    exploration_mode: z.string(),
    diversity_policy: z.string(),
  }),
  candidate_sources: z.array(
    z.object({
      source: z.string(),
      status: z.string(),
      candidates: z.number(),
      model_version: z.string().nullable(),
      detail: z.string().nullable(),
    }),
  ),
  context: z.record(z.string(), z.unknown()).optional(),
  experiment: z.string().nullable().optional(),
  variant: z.string().nullable().optional(),
});
export type PersonalizedResponse = z.infer<typeof PersonalizedResponseSchema>;

export const MoodSchema = z.object({
  key: z.string(),
  title: z.string(),
  description: z.string(),
  genres: z.array(z.string()),
});
export type Mood = z.infer<typeof MoodSchema>;
export const MoodListSchema = z.object({ moods: z.array(MoodSchema) });
export const MoodMixSchema = RecommendationResponseSchema.extend({
  mood: MoodSchema,
  personalized: z.boolean(),
});
export type MoodMix = z.infer<typeof MoodMixSchema>;

export const BecauseYouListenedSchema = z.object({
  sections: z.array(
    z.object({
      seed: TrackSummarySchema,
      source: z.string(),
      recommendations: z.array(RecommendationItemSchema),
    }),
  ),
});
export type BecauseYouListened = z.infer<typeof BecauseYouListenedSchema>;

// --- users: preferences, profile, analytics, interactions -------------------------------------

export const ExplorationModeSchema = z.enum([
  "familiar",
  "balanced",
  "explorer",
]);
export type ExplorationMode = z.infer<typeof ExplorationModeSchema>;

export const PreferencesSchema = z.object({
  exploration_mode: ExplorationModeSchema.nullable(),
  personalization_enabled: z.boolean(),
  preferred_artists: z.array(
    z.object({ artist_id: z.uuid(), name: z.string() }),
  ),
  excluded_artists: z.array(
    z.object({ artist_id: z.uuid(), name: z.string() }),
  ),
  preferred_genres: z.array(z.string()),
  excluded_genres: z.array(z.string()),
  preferred_moods: z.array(z.string()),
  updated_at: z.string().nullable(),
});
export type Preferences = z.infer<typeof PreferencesSchema>;

export interface PreferencesUpdate {
  exploration_mode: ExplorationMode | null;
  personalization_enabled: boolean;
  preferred_artists: string[];
  excluded_artists: string[];
  preferred_genres: string[];
  excluded_genres: string[];
  preferred_moods: string[];
}

const AffinitySchema = z.object({
  artist_id: z.uuid(),
  name: z.string(),
  score: z.number(),
});

export const TasteProfileSchema = z.object({
  user_id: z.uuid(),
  profile_version: z.string(),
  genre_affinity: z.array(z.object({ genre: z.string(), score: z.number() })),
  artist_affinity: z.array(AffinitySchema),
  negative_artists: z.array(AffinitySchema),
  listening_frequency: z.record(z.string(), z.number()),
  exploration_preference: z.number(),
  exploration_mode: ExplorationModeSchema.nullable(),
  discovery_target: z.number(),
  history_size: z.number(),
  interaction_count: z.number(),
  last_event_at: z.string().nullable(),
});
export type TasteProfile = z.infer<typeof TasteProfileSchema>;

export const TasteAnalyticsSchema = z.object({
  overview: z.string().nullable(),
  events: z.number(),
  genres: z.array(z.object({ genre: z.string(), score: z.number() })),
  artists: z.array(
    z.object({
      artist_id: z.uuid(),
      name: z.string(),
      score: z.number(),
      playbacks: z.number(),
    }),
  ),
  trends: z.array(
    z.object({
      week_start: z.string(),
      playbacks: z.number(),
      distinct_tracks: z.number(),
      new_artists: z.number(),
    }),
  ),
  emerging: z.array(
    z.object({
      genre: z.string(),
      recent_share: z.number(),
      earlier_share: z.number(),
      change: z.number(),
    }),
  ),
  fading: z.array(
    z.object({
      genre: z.string(),
      recent_share: z.number(),
      earlier_share: z.number(),
      change: z.number(),
    }),
  ),
  discovery: z
    .object({
      new_artists_30d: z.number(),
      new_genres_30d: z.number(),
      saved_tracks: z.number(),
      liked_tracks: z.number(),
      exploration_preference: z.number(),
      discovery_target: z.number(),
    })
    .nullable(),
});
export type TasteAnalytics = z.infer<typeof TasteAnalyticsSchema>;

export const EventTypeSchema = z.enum([
  "play",
  "complete",
  "replay",
  "skip",
  "like",
  "unlike",
  "dislike",
  "undislike",
  "save",
  "unsave",
  "playlist_add",
]);
export type EventType = z.infer<typeof EventTypeSchema>;

export const InteractionSchema = z.object({
  id: z.uuid(),
  track_id: z.uuid(),
  event_type: EventTypeSchema,
  occurred_at: z.string(),
  track: TrackSummarySchema.nullable().optional(),
});
export const InteractionHistorySchema = z.object({
  items: z.array(InteractionSchema),
  next_before: z.string().nullable(),
});
export type InteractionHistory = z.infer<typeof InteractionHistorySchema>;

export const InteractionsRecordedSchema = z.object({
  recorded: z.number(),
  duplicates: z.number(),
  profile: TasteProfileSchema,
});

export const FeedbackStateSchema = z.object({
  liked: z.boolean(),
  disliked: z.boolean(),
  saved: z.boolean(),
});
export type FeedbackState = z.infer<typeof FeedbackStateSchema>;
export const FeedbackStatesSchema = z.object({
  states: z.record(z.string(), FeedbackStateSchema),
});

// --- playlists -------------------------------------------------------------------------------

export const CollectionSchema = z.enum([
  "for_you",
  "mood",
  "hidden_gems",
  "genre",
  "artist_radio",
  "custom",
]);
export type Collection = z.infer<typeof CollectionSchema>;

export interface Generator {
  collection: Collection;
  mood?: string;
  genre?: string;
  artist_id?: string;
  prompt?: string;
  exploration_level?: number | null;
  size?: number;
}

export const PlaylistSummarySchema = z.object({
  id: z.uuid(),
  name: z.string(),
  description: z.string().nullable(),
  kind: z.enum(["manual", "generated"]),
  collection: CollectionSchema.nullable(),
  track_count: z.number(),
  duration_ms: z.number().nullable(),
  artwork_urls: z.array(z.string()),
  created_at: z.string(),
  updated_at: z.string(),
});
export type PlaylistSummary = z.infer<typeof PlaylistSummarySchema>;

export const PlaylistDetailSchema = PlaylistSummarySchema.extend({
  generator: z.record(z.string(), z.unknown()).nullable(),
  tracks: z.array(
    TrackSummarySchema.extend({ position: z.number(), added_at: z.string() }),
  ),
});
export type PlaylistDetail = z.infer<typeof PlaylistDetailSchema>;
export type PlaylistTrack = PlaylistDetail["tracks"][number];

export const PlaylistListSchema = z.object({
  playlists: z.array(PlaylistSummarySchema),
});

// --- integrations (Milestone 5) ------------------------------------------------------------

export const ImportRunSchema = z.object({
  id: z.uuid(),
  provider: z.string(),
  status: z.enum(["running", "completed", "failed"]),
  fetched: z.number(),
  matched: z.number(),
  imported: z.number(),
  duplicates: z.number(),
  error: z.string().nullable(),
  started_at: z.string(),
  finished_at: z.string().nullable(),
});
export type ImportRun = z.infer<typeof ImportRunSchema>;

export const ProviderSchema = z.object({
  provider: z.string(),
  name: z.string(),
  description: z.string(),
  auth: z.enum(["token", "oauth", "none"]),
  capabilities: z.array(z.string()),
  available: z.boolean(),
  max_export_tracks: z.number(),
  connection: z
    .object({
      status: z.enum(["active", "reauth_required"]),
      external_name: z.string().nullable(),
      scopes: z.array(z.string()),
      connected_at: z.string(),
      last_import: ImportRunSchema.nullable(),
    })
    .nullable(),
});
export type Provider = z.infer<typeof ProviderSchema>;
export const ProviderListSchema = z.object({
  providers: z.array(ProviderSchema),
  tokens_configured: z.boolean(),
});

export const PlaylistExportSchema = z.object({
  provider: z.string(),
  status: z.enum(["running", "completed", "failed"]),
  external_url: z.string().nullable(),
  exported: z.number(),
  unmatched: z.number(),
  attempts: z.number(),
  error: z.string().nullable(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
});
export type PlaylistExport = z.infer<typeof PlaylistExportSchema>;
export const PlaylistExportListSchema = z.object({
  exports: z.array(PlaylistExportSchema),
});

export const RecordingSearchSchema = z.object({
  query: z.string(),
  results: z.array(
    z.object({
      mbid: z.string(),
      title: z.string(),
      artist: z.string(),
      release: z.string().nullable(),
      length_ms: z.number().nullable(),
      url: z.string(),
      track_id: z.uuid().nullable(),
    }),
  ),
});
export const AuthorizeSchema = z.object({ url: z.string() });

// --- prompt playlists (Milestone 6) ----------------------------------------------------------

const ArtistRefSchema = z.object({ id: z.uuid(), name: z.string() });
const BoundsSchema = z.tuple([z.number().nullable(), z.number().nullable()]);

export const CustomResponseSchema = RecommendationResponseSchema.extend({
  prompt: z.string(),
  personalized: z.boolean(),
  interpretation: z.object({
    genres: z.array(z.string()),
    excluded_genres: z.array(z.string()),
    moods: z.array(z.string()),
    artists: z.array(ArtistRefSchema),
    excluded_artists: z.array(ArtistRefSchema),
    tempo: BoundsSchema,
    danceability: BoundsSchema,
    years: BoundsSchema,
    popularity: z.string().nullable(),
    exploration_level: z.number().nullable(),
    ignored: z.array(z.string()),
    summary: z.string(),
  }),
});
export type CustomResponse = z.infer<typeof CustomResponseSchema>;
export type Interpretation = CustomResponse["interpretation"];

export interface CustomRequest {
  prompt: string;
  limit?: number;
  exploration_level?: number | null;
  exclude_previously_heard?: boolean;
  exclude?: string[];
}
