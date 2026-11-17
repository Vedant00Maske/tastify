import type { QueueTrack } from "@/stores/player";
import type { RecommendationItem, TrackSummary } from "@/types/api";

/** What every track component renders: catalogue tracks and recommendations map onto it. */
export interface DisplayTrack {
  id: string;
  title: string;
  artist: string;
  artistId?: string | null;
  artworkUrl?: string | null;
  album?: string | null;
  durationMs?: number | null;
  reason?: string;
  discovery?: boolean;
  sources?: string[];
}

export function fromRecommendation(item: RecommendationItem): DisplayTrack {
  return {
    id: item.track_id,
    title: item.title,
    artist: item.artist,
    artistId: item.artist_id,
    artworkUrl: item.artwork_url,
    album: item.album,
    reason: item.reason,
    discovery: item.discovery,
    sources: item.sources?.map((s) => s.source),
  };
}

export function fromSummary(track: TrackSummary): DisplayTrack {
  return {
    id: track.id,
    title: track.title,
    artist: track.artist,
    artistId: track.artist_id,
    artworkUrl: track.artwork_url,
    album: track.album_title,
    durationMs: track.duration_ms,
  };
}

export function toQueue(track: DisplayTrack): QueueTrack {
  return {
    id: track.id,
    title: track.title,
    artist: track.artist,
    artistId: track.artistId,
    artworkUrl: track.artworkUrl,
  };
}

const SOURCE_LABELS: Record<string, string> = {
  collaborative_item: "Co-listened",
  collaborative_mf: "Listeners like you",
  listening_profile: "Your taste profile",
  content_based: "Similar sound",
  exploration: "New artist",
  popularity: "Popular",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source.replaceAll("_", " ");
}
