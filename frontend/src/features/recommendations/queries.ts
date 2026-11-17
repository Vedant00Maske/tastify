"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import { keys } from "@/lib/query-keys";
import { catalogue, recommendations } from "@/services/api";
import type { ExplorationMode } from "@/types/api";

const FIVE_MINUTES = 5 * 60_000;

export function useForYou(limit = 25, exploration?: ExplorationMode) {
  return useQuery({
    queryKey: keys.forYou(limit, exploration),
    queryFn: () => recommendations.forYou(limit, exploration),
    staleTime: FIVE_MINUTES,
  });
}

export function useHiddenGems(limit = 20) {
  return useQuery({
    queryKey: keys.hiddenGems(limit),
    queryFn: () => recommendations.hiddenGems(limit),
    staleTime: FIVE_MINUTES,
  });
}

export function useBecauseYouListened() {
  return useQuery({
    queryKey: keys.because,
    queryFn: () => recommendations.becauseYouListened(2, 10),
    staleTime: FIVE_MINUTES,
  });
}

export function useMoods() {
  return useQuery({
    queryKey: keys.moods,
    queryFn: recommendations.moods,
    staleTime: Infinity,
  });
}

/**
 * A mood mix. Each regenerate is a new `round` that leaves out the tracks of earlier rounds
 * (`exclude`), so the user gets a fresh mix instead of the same deterministic one.
 */
export function useMoodMix(
  mood: string,
  limit = 25,
  round = 0,
  exclude: string[] = [],
) {
  return useQuery({
    queryKey: keys.mood(mood, limit, round),
    queryFn: () => recommendations.mood(mood, limit, exclude),
    staleTime: FIVE_MINUTES,
    placeholderData: (previous) => previous,
  });
}

export function useSimilarTracks(trackId: string) {
  return useQuery({
    queryKey: keys.similar(trackId),
    queryFn: () => recommendations.similar(trackId, 20),
  });
}

export function useSimilarArtists(artistId: string) {
  return useQuery({
    queryKey: keys.similarArtists(artistId),
    queryFn: () => recommendations.similarArtists(artistId, 12),
  });
}

export function useArtistRadio(artistId: string) {
  return useQuery({
    queryKey: keys.artistRadio(artistId),
    queryFn: () => recommendations.artistRadio(artistId, 25),
  });
}

export function useGenreRecommendations(genre: string | null) {
  return useQuery({
    queryKey: keys.genreRecs(genre ?? ""),
    queryFn: () => recommendations.genre(genre ?? "", 20),
    enabled: !!genre,
  });
}

export function usePopular(kind: "all_time" | "trending" = "all_time") {
  return useQuery({
    queryKey: keys.popular(kind),
    queryFn: () => recommendations.popular(20, kind),
    staleTime: FIVE_MINUTES,
  });
}

/** Surprise Me: a fresh random pick on every call, so it is a mutation, not a cached query. */
export function useSurprise() {
  return useMutation({ mutationFn: recommendations.surprise });
}

export function useGenres() {
  return useQuery({
    queryKey: keys.genres,
    queryFn: () => catalogue.genres(60),
    staleTime: Infinity,
  });
}

export function useTrack(id: string) {
  return useQuery({
    queryKey: keys.track(id),
    queryFn: () => catalogue.track(id),
  });
}

export function useArtist(id: string) {
  return useQuery({
    queryKey: keys.artist(id),
    queryFn: () => catalogue.artist(id),
  });
}

export function useTrackSearch(q: string) {
  return useQuery({
    queryKey: keys.trackSearch(q),
    queryFn: () => catalogue.searchTracks(q, 20),
    enabled: q.trim().length >= 2,
    placeholderData: (previous) => previous,
  });
}

export function useArtistSearch(q: string, limit = 12) {
  return useQuery({
    queryKey: keys.artistSearch(q, limit),
    queryFn: () => catalogue.searchArtists(q, limit),
    enabled: q.trim().length >= 2,
    placeholderData: (previous) => previous,
  });
}
