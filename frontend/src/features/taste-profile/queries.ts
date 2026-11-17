"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { keys } from "@/lib/query-keys";
import { account } from "@/services/api";
import type { Preferences, PreferencesUpdate } from "@/types/api";

export function useTaste() {
  return useQuery({ queryKey: keys.taste, queryFn: account.taste });
}

export function useTasteProfile() {
  return useQuery({
    queryKey: keys.tasteProfile,
    queryFn: account.tasteProfile,
  });
}

export function usePreferences() {
  return useQuery({ queryKey: keys.preferences, queryFn: account.preferences });
}

/** The PUT body that keeps everything as it is (edit one field on top of it). */
export function toUpdate(preferences: Preferences): PreferencesUpdate {
  return {
    exploration_mode: preferences.exploration_mode,
    personalization_enabled: preferences.personalization_enabled,
    preferred_artists: preferences.preferred_artists.map((a) => a.artist_id),
    excluded_artists: preferences.excluded_artists.map((a) => a.artist_id),
    preferred_genres: preferences.preferred_genres,
    excluded_genres: preferences.excluded_genres,
    preferred_moods: preferences.preferred_moods,
  };
}

/** Preferences change the taste profile, so every personalized view is refreshed. */
export function useUpdatePreferences() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: account.updatePreferences,
    onSuccess: (preferences) => {
      client.setQueryData(keys.preferences, preferences);
      for (const key of [
        keys.tasteProfile,
        keys.taste,
        keys.forYouAll,
        keys.because,
        ["hidden-gems"],
        ["mood"],
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}
