"use client";

import { EyeOff } from "lucide-react";
import { motion } from "motion/react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { useFeedback } from "@/features/feedback/queries";
import {
  toUpdate,
  usePreferences,
  useUpdatePreferences,
} from "@/features/taste-profile/queries";
import { easeOutSoft } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { usePlayer } from "@/stores/player";

export interface HideableTrack {
  id: string;
  title: string;
  artist: string;
  artistId?: string | null;
  requestId?: string;
}

interface HideOnDislike {
  isHidden: (trackId: string) => boolean;
  /** Collapse the track wherever it is shown and drop it from the player queue. */
  hide: (track: HideableTrack) => void;
  restore: (trackId: string) => void;
  /** True once for the track the listener just hid, so its notice can take focus. */
  takeFocus: (trackId: string) => boolean;
}

const HideOnDislikeContext = createContext<HideOnDislike | null>(null);

/**
 * Pages that wrap their content in this provider turn a dislike into a visible result: the track
 * collapses to a notice with Undo (and "Exclude <artist>"), and it leaves the player queue.
 * Without the provider, feedback buttons keep their usual behaviour.
 */
export function HideOnDislikeProvider({ children }: { children: ReactNode }) {
  const [hidden, setHidden] = useState<Record<string, HideableTrack>>({});
  const [announcement, setAnnouncement] = useState("");
  const focusNext = useRef<string | null>(null);
  const removeFromQueue = usePlayer((s) => s.remove);

  const hide = useCallback(
    (track: HideableTrack) => {
      setHidden((current) => ({ ...current, [track.id]: track }));
      focusNext.current = track.id;
      removeFromQueue(track.id);
      setAnnouncement(`${track.title} hidden. Undo is available.`);
    },
    [removeFromQueue],
  );
  const restore = useCallback((trackId: string) => {
    setHidden((current) => {
      const next = { ...current };
      delete next[trackId];
      return next;
    });
  }, []);
  const value = useMemo<HideOnDislike>(
    () => ({
      isHidden: (trackId) => trackId in hidden,
      hide,
      restore,
      takeFocus: (trackId) => {
        if (focusNext.current !== trackId) return false;
        focusNext.current = null;
        return true;
      },
    }),
    [hidden, hide, restore],
  );
  return (
    <HideOnDislikeContext.Provider value={value}>
      {children}
      <p role="status" className="sr-only">
        {announcement}
      </p>
    </HideOnDislikeContext.Provider>
  );
}

export function useHideOnDislike(): HideOnDislike | null {
  return useContext(HideOnDislikeContext);
}

/** What a hidden track collapses to: Undo, and hiding every track by its artist. */
export function HiddenTrackNotice({
  track,
  variant,
}: {
  track: HideableTrack;
  variant: "row" | "card";
}) {
  const hider = useHideOnDislike();
  const feedback = useFeedback();
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const removeFromQueue = usePlayer((s) => s.remove);
  const rootRef = useRef<HTMLDivElement>(null);
  const undoRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (hider?.takeFocus(track.id)) undoRef.current?.focus();
    // Only on mount: the notice replaces the dislike button the listener just pressed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /**
   * The notice is about to unmount, so keyboard focus moves somewhere that survives it: the list
   * or row that contained it (focus would otherwise fall back to the page body).
   */
  const container = () =>
    rootRef.current?.closest<HTMLElement>(
      "ol, [role='list'], [role='region'], section",
    ) ?? null;
  const focusContainer = (target: HTMLElement | null) => {
    if (!target) return;
    if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
    target.focus();
  };

  const undo = () => {
    const list = container();
    hider?.restore(track.id);
    // Back to the restored track's dislike button once it renders again.
    requestAnimationFrame(() => {
      const button = Array.from(
        list?.querySelectorAll<HTMLButtonElement>("button[aria-label]") ?? [],
      ).find((b) =>
        [`Dislike ${track.title}`, `Remove dislike of ${track.title}`].includes(
          b.getAttribute("aria-label") ?? "",
        ),
      );
      if (button) button.focus();
      else focusContainer(list);
    });
    feedback.mutate(
      {
        trackId: track.id,
        eventType: "undislike",
        requestId: track.requestId,
      },
      { onError: () => toast.error("That did not save. Try again.") },
    );
  };

  const hideArtist = () => {
    const current = preferences.data;
    const artistId = track.artistId;
    if (!current || !artistId) return;
    const before = toUpdate(current);
    if (before.excluded_artists.includes(artistId)) return;
    const list = container();
    update.mutate(
      { ...before, excluded_artists: [...before.excluded_artists, artistId] },
      {
        onSuccess: (saved) => {
          // The refreshed mix drops this notice with the artist's tracks.
          focusContainer(list);
          for (const queued of usePlayer.getState().queue) {
            if (queued.artistId === artistId) removeFromQueue(queued.id);
          }
          toast(`${track.artist} excluded`, {
            description:
              "Never recommended, in any mix. You can change this in Settings.",
            action: {
              label: "Undo",
              onClick: () =>
                update.mutate({
                  ...toUpdate(saved),
                  excluded_artists: toUpdate(saved).excluded_artists.filter(
                    (id) => id !== artistId,
                  ),
                }),
            },
          });
        },
        onError: () =>
          toast.error(`Could not exclude ${track.artist}. Try again.`),
      },
    );
  };

  return (
    <motion.div
      ref={rootRef}
      role="group"
      aria-label={`${track.title} hidden`}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2, ease: easeOutSoft }}
      className={cn(
        "flex border border-dashed border-border text-support text-fg-secondary",
        variant === "row"
          ? "flex-wrap items-center gap-x-3 gap-y-2 rounded-button px-3 py-2"
          : "h-full min-h-40 flex-col justify-between gap-4 rounded-card p-3",
      )}
    >
      <p className="flex min-w-0 items-center gap-2">
        <EyeOff className="size-4 shrink-0 text-fg-muted" aria-hidden />
        <span className="min-w-0 truncate">
          Hidden: <span className="text-fg">{track.title}</span>
        </span>
      </p>
      <div
        className={cn(
          "flex flex-wrap items-center gap-2",
          variant === "row" && "ml-auto",
        )}
      >
        <Button ref={undoRef} size="sm" variant="secondary" onClick={undo}>
          Undo
        </Button>
        {track.artistId ? (
          <Button
            size="sm"
            variant="ghost"
            disabled={!preferences.data || update.isPending}
            onClick={hideArtist}
          >
            Exclude {track.artist}
          </Button>
        ) : null}
      </div>
    </motion.div>
  );
}
