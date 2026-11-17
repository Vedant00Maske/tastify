import { create } from "zustand";

/**
 * Player UI state. There is no audio source until provider integrations (Milestone 5): the player
 * keeps a queue and shows the current track with links to listen elsewhere. It never pretends to
 * play, so it records no plays or skips.
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

/** Search links to listen to a track elsewhere (no provider account needed). */
export function listenLinks(
  track: QueueTrack,
): { label: string; href: string }[] {
  const query = encodeURIComponent(`${track.artist} ${track.title}`);
  return [
    {
      label: "YouTube",
      href: `https://www.youtube.com/results?search_query=${query}`,
    },
    {
      label: "MusicBrainz",
      href: `https://musicbrainz.org/search?type=recording&query=${query}`,
    },
  ];
}
