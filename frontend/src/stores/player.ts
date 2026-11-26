import { create } from "zustand";

/**
 * Player UI state. SONIQUEO does not play audio yet (in-app playback is planned): the player keeps
 * a queue and shows the current track with links to listen elsewhere. It never pretends to play,
 * so it records no plays or skips.
 */
export interface QueueTrack {
  id: string;
  title: string;
  artist: string;
  artistId?: string | null;
  artworkUrl?: string | null;
}

interface PlayerState {
  queue: QueueTrack[];
  index: number;
  play: (tracks: QueueTrack[], start?: number) => void;
  playShuffled: (tracks: QueueTrack[]) => void;
  enqueue: (track: QueueTrack) => void;
  /** Drop a track (e.g. after a dislike); the current position stays on the same next track. */
  remove: (trackId: string) => void;
  next: () => void;
  previous: () => void;
  jump: (index: number) => void;
  shuffle: () => void;
  clear: () => void;
}

export const usePlayer = create<PlayerState>((set) => ({
  queue: [],
  index: 0,
  play: (tracks, start = 0) =>
    set({
      queue: tracks,
      index: Math.min(Math.max(start, 0), Math.max(tracks.length - 1, 0)),
    }),
  playShuffled: (tracks) => {
    const queue = [...tracks];
    for (let i = queue.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [queue[i], queue[j]] = [queue[j], queue[i]];
    }
    set({ queue, index: 0 });
  },
  enqueue: (track) =>
    set((state) =>
      state.queue.some((t) => t.id === track.id)
        ? state
        : { queue: [...state.queue, track] },
    ),
  remove: (trackId) =>
    set((state) => {
      const at = state.queue.findIndex((t) => t.id === trackId);
      if (at === -1) return state;
      const queue = state.queue.filter((_, i) => i !== at);
      if (!queue.length) return { queue, index: 0 };
      // Removing an earlier track shifts the current one back; removing the current track lands
      // on the track that followed it (or the new last track).
      const index = at < state.index ? state.index - 1 : state.index;
      return { queue, index: Math.min(index, queue.length - 1) };
    }),
  next: () =>
    set((state) => ({
      index: Math.min(state.index + 1, state.queue.length - 1),
    })),
  previous: () => set((state) => ({ index: Math.max(state.index - 1, 0) })),
  jump: (index) =>
    set((state) => ({
      index: Math.min(Math.max(index, 0), state.queue.length - 1),
    })),
  shuffle: () =>
    set((state) => {
      if (state.queue.length < 2) return state;
      const current = state.queue[state.index];
      const rest = state.queue.filter((_, i) => i !== state.index);
      for (let i = rest.length - 1; i > 0; i -= 1) {
        const j = Math.floor(Math.random() * (i + 1));
        [rest[i], rest[j]] = [rest[j], rest[i]];
      }
      return { queue: [current, ...rest], index: 0 };
    }),
  clear: () => set({ queue: [], index: 0 }),
}));

export function currentTrack(state: PlayerState): QueueTrack | null {
  return state.queue[state.index] ?? null;
}

/**
 * Search links to listen to a track elsewhere (no provider account needed). Only services you can
 * actually listen on: MusicBrainz is a database, so it is not one of them.
 */
export function listenLinks(
  track: QueueTrack,
): { label: string; href: string }[] {
  const query = encodeURIComponent(`${track.artist} ${track.title}`);
  return [
    {
      label: "Spotify",
      href: `https://open.spotify.com/search/${query}`,
    },
    {
      label: "YouTube",
      href: `https://www.youtube.com/results?search_query=${query}`,
    },
  ];
}
