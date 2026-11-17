"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { keys } from "@/lib/query-keys";
import { playlists } from "@/services/api";
import type { PlaylistDetail } from "@/types/api";

export function usePlaylists() {
  return useQuery({ queryKey: keys.playlists, queryFn: playlists.list });
}

export function usePlaylist(id: string) {
  return useQuery({
    queryKey: keys.playlist(id),
    queryFn: () => playlists.get(id),
  });
}

export function usePlaylistSuggestions(id: string, enabled: boolean) {
  return useQuery({
    queryKey: keys.suggestions(id),
    queryFn: () => playlists.suggestions(id, 8),
    enabled,
  });
}

/** Every playlist mutation returns the updated playlist: store it and refresh the library. */
function useStore() {
  const client = useQueryClient();
  return (playlist: PlaylistDetail) => {
    client.setQueryData(keys.playlist(playlist.id), playlist);
    void client.invalidateQueries({ queryKey: keys.playlists });
    void client.invalidateQueries({ queryKey: keys.suggestions(playlist.id) });
  };
}

export function useCreatePlaylist() {
  const store = useStore();
  return useMutation({ mutationFn: playlists.create, onSuccess: store });
}

export function useUpdatePlaylist(id: string) {
  const store = useStore();
  return useMutation({
    mutationFn: (body: { name?: string; description?: string | null }) =>
      playlists.update(id, body),
    onSuccess: store,
  });
}

export function useAddToPlaylist() {
  const store = useStore();
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      playlistId,
      trackIds,
    }: {
      playlistId: string;
      trackIds: string[];
    }) => playlists.addTracks(playlistId, trackIds),
    onSuccess: (playlist) => {
      store(playlist);
      // Adding is positive feedback: the taste profile changed.
      void client.invalidateQueries({ queryKey: keys.taste });
      void client.invalidateQueries({ queryKey: keys.tasteProfile });
    },
  });
}

export function useRemoveFromPlaylist(id: string) {
  const store = useStore();
  return useMutation({
    mutationFn: (trackId: string) => playlists.removeTrack(id, trackId),
    onSuccess: store,
  });
}

export function useReorderPlaylist(id: string) {
  const store = useStore();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (trackIds: string[]) => playlists.reorder(id, trackIds),
    // Show the new order at once; the server's answer replaces it.
    onMutate: (trackIds) => {
      const previous = client.getQueryData<PlaylistDetail>(keys.playlist(id));
      if (previous) {
        const byId = new Map(previous.tracks.map((t) => [t.id, t]));
        client.setQueryData(keys.playlist(id), {
          ...previous,
          tracks: trackIds.flatMap((tid, position) => {
            const track = byId.get(tid);
            return track ? [{ ...track, position }] : [];
          }),
        });
      }
      return { previous };
    },
    onError: (_error, _ids, context) => {
      if (context?.previous)
        client.setQueryData(keys.playlist(id), context.previous);
    },
    onSuccess: store,
  });
}

export function useRegeneratePlaylist(id: string) {
  const store = useStore();
  return useMutation({
    mutationFn: () => playlists.regenerate(id),
    onSuccess: store,
  });
}

export function useDeletePlaylist() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: playlists.remove,
    onSuccess: () =>
      void client.invalidateQueries({ queryKey: keys.playlists }),
  });
}
