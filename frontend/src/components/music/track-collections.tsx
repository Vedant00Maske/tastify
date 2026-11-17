"use client";

import { motion } from "motion/react";
import type { ReactNode } from "react";

import { Carousel } from "@/components/layout/page";
import { Skeleton } from "@/components/ui/states";
import { useFeedbackStates } from "@/features/feedback/queries";
import { usePlayer } from "@/stores/player";

import { TrackCard, TrackRow } from "./cards";
import { toQueue, type DisplayTrack } from "./display";

/** Staggered reveal of recommendation cards (250 ms, §7). */
const reveal = {
  hidden: { opacity: 0, y: 8 },
  shown: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { duration: 0.25, delay: Math.min(i, 10) * 0.03 },
  }),
};

function usePlayFrom(tracks: DisplayTrack[]) {
  const play = usePlayer((s) => s.play);
  return (index: number) => play(tracks.map(toQueue), index);
}

/** Recommendation cards in a responsive grid or a carousel, with feedback state and playback. */
export function TrackCards({
  tracks,
  layout = "grid",
  label,
  showReason = true,
}: {
  tracks: DisplayTrack[];
  layout?: "grid" | "carousel";
  label: string;
  showReason?: boolean;
}) {
  const stateOf = useFeedbackStates(tracks.map((t) => t.id));
  const playFrom = usePlayFrom(tracks);
  const cards = tracks.map((track, i) => (
    <motion.div
      key={track.id}
      custom={i}
      variants={reveal}
      initial="hidden"
      animate="shown"
    >
      <TrackCard
        track={track}
        state={stateOf(track.id)}
        onPlay={() => playFrom(i)}
        showReason={showReason}
        className="h-full"
      />
    </motion.div>
  ));
  if (layout === "carousel") return <Carousel label={label}>{cards}</Carousel>;
  return (
    <div
      role="list"
      aria-label={label}
      className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 2xl:grid-cols-6 [&>*]:h-full"
    >
      {cards}
    </div>
  );
}

export function TrackRows({
  tracks,
  label,
  showReason = false,
  actions,
}: {
  tracks: DisplayTrack[];
  label: string;
  showReason?: boolean;
  actions?: (track: DisplayTrack) => ReactNode;
}) {
  const stateOf = useFeedbackStates(tracks.map((t) => t.id));
  const playFrom = usePlayFrom(tracks);
  return (
    <div role="list" aria-label={label} className="flex flex-col">
      {tracks.map((track, i) => (
        <div role="listitem" key={track.id}>
          <TrackRow
            track={track}
            index={i}
            state={stateOf(track.id)}
            onPlay={() => playFrom(i)}
            showReason={showReason}
            actions={actions?.(track)}
          />
        </div>
      ))}
    </div>
  );
}

export function CardsSkeleton({
  count = 5,
  layout = "grid",
}: {
  count?: number;
  layout?: "grid" | "carousel";
}) {
  const items = Array.from({ length: count }, (_, i) => (
    <div key={i} className="flex flex-col gap-3 rounded-card bg-surface p-3">
      <Skeleton className="aspect-square rounded-button" />
      <Skeleton className="h-4 w-3/4" />
      <Skeleton className="h-3 w-1/2" />
    </div>
  ));
  if (layout === "carousel") {
    return (
      <div
        aria-busy
        className="flex gap-4 overflow-hidden [&>*]:w-[44vw] [&>*]:max-w-[220px] [&>*]:shrink-0 sm:[&>*]:w-[210px]"
      >
        {items}
      </div>
    );
  }
  return (
    <div
      aria-busy
      className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5"
    >
      {items}
    </div>
  );
}

export function RowsSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div aria-busy className="flex flex-col gap-2">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="flex items-center gap-3 px-2 py-2">
          <Skeleton className="size-12 rounded-button-sm" />
          <div className="flex flex-1 flex-col gap-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-1/4" />
          </div>
        </div>
      ))}
    </div>
  );
}
