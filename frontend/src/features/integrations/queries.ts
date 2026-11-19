"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { keys } from "@/lib/query-keys";
import { hardNavigate } from "@/lib/navigation";
import { integrations } from "@/services/api";

export function useIntegrations() {
  return useQuery({ queryKey: keys.integrations, queryFn: integrations.list });
}

export function useConnectToken(provider: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (token: string) => integrations.connectToken(provider, token),
    onSuccess: (list) => client.setQueryData(keys.integrations, list),
  });
}

/** OAuth: the provider's sign-in page takes over the tab and comes back to Settings. */
export function useAuthorize() {
  return useMutation({
    mutationFn: integrations.authorize,
    onSuccess: ({ url }) => hardNavigate(url),
  });
}

/** Imported history changes the taste profile, so every personalized view is refreshed. */
export function useImportHistory(provider: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => integrations.importHistory(provider),
    onSettled: () => {
      for (const key of [
        keys.integrations,
        keys.taste,
        keys.tasteProfile,
        keys.forYouAll,
        keys.because,
        ["history"],
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export function useDisconnect(provider: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (deleteImported: boolean) =>
      integrations.disconnect(provider, deleteImported),
    onSettled: () => {
      for (const key of [
        keys.integrations,
        keys.taste,
        keys.tasteProfile,
        keys.forYouAll,
      ]) {
        void client.invalidateQueries({ queryKey: key });
      }
    },
  });
}

export function usePlaylistExports(playlistId: string) {
  return useQuery({
    queryKey: keys.exports(playlistId),
    queryFn: () => integrations.exports(playlistId),
  });
}

export function useExportPlaylist(playlistId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (provider: string) =>
      integrations.exportPlaylist(playlistId, provider),
    onSettled: () =>
      void client.invalidateQueries({ queryKey: keys.exports(playlistId) }),
  });
}

export function useMusicBrainzSearch(q: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.musicbrainz(q),
    queryFn: () => integrations.searchMusicBrainz(q),
    enabled: enabled && q.trim().length >= 2,
    staleTime: 10 * 60_000,
    retry: false,
  });
}
