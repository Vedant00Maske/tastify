"use client";

import { ArrowUpRight, Play, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import type { ReactNode } from "react";

import {
  AddToPlaylist,
  FeedbackButtons,
} from "@/components/feedback/feedback-buttons";
import { Pill } from "@/components/ui/states";
import { cn, formatDuration } from "@/lib/utils";
import type { FeedbackState } from "@/types/api";

import { CollageArtwork, GeneratedCover, TrackArtwork } from "./artwork";
import { sourceLabel, type DisplayTrack } from "./display";

const hover = { whileHover: { scale: 1.02 }, transition: { duration: 0.2 } };

/** A track with artwork, its reason and feedback controls (recommendation grids, carousels). */
export function TrackCard({
  track,
  state,
  onPlay,
  showReason = true,
  className,
}: {
  track: DisplayTrack;
  state: FeedbackState;
  onPlay: () => void;
  showReason?: boolean;
  className?: string;
}) {
  return (
    <motion.article
      {...hover}
      className={cn(
        "group flex flex-col gap-3 rounded-card bg-surface p-3 shadow-card transition-colors duration-200 hover:bg-surface-hover",
        className,
      )}
    >
      <div className="relative">
        <TrackArtwork
          src={track.artworkUrl}
          seed={track.id}
          label={track.artist}
          alt={`${track.title} by ${track.artist}`}
          sizes="(max-width: 640px) 45vw, 220px"
        />
        <button
          type="button"
          onClick={onPlay}
          aria-label={`Play ${track.title} by ${track.artist}`}
          className="absolute right-2 bottom-2 grid size-11 translate-y-1 place-items-center rounded-full bg-accent text-on-accent opacity-0 shadow-elevated transition-all duration-200 group-hover:translate-y-0 group-hover:opacity-100 focus-visible:translate-y-0 focus-visible:opacity-100"
        >
          <Play className="size-4 fill-current" />
        </button>
        {track.discovery ? (
          <Pill
            active
            className="absolute top-2 left-2 bg-background/80 backdrop-blur"
          >
            <Sparkles className="size-3" /> New artist
          </Pill>
        ) : null}
      </div>
      <div className="min-w-0">
        <Link
          href={`/tracks/${track.id}`}
          className="block truncate font-display text-card font-semibold hover:underline"
        >
          {track.title}
        </Link>
        {track.artistId ? (
          <Link
            href={`/artists/${track.artistId}`}
            className="block truncate text-support text-fg-secondary hover:text-fg"
          >
            {track.artist}
          </Link>
        ) : (
          <p className="truncate text-support text-fg-secondary">
            {track.artist}
          </p>
        )}
      </div>
      {showReason && track.reason ? (
        <p
          className="line-clamp-2 text-meta text-fg-muted"
          title={track.reason}
        >
          {track.reason}
        </p>
      ) : null}
      <div className="mt-auto flex items-center justify-between">
        <FeedbackButtons
          trackId={track.id}
          title={track.title}
          state={state}
          requestId={track.requestId}
        />
        <AddToPlaylist trackId={track.id} title={track.title} />
      </div>
    </motion.article>
  );
}

/** A compact list row (playlists, search results, mixes). */
export function TrackRow({
  track,
  index,
  state,
  onPlay,
  actions,
  showReason = false,
}: {
  track: DisplayTrack;
  index?: number;
  state?: FeedbackState;
  onPlay: () => void;
  actions?: ReactNode;
  showReason?: boolean;
}) {
  const duration = formatDuration(track.durationMs);
  return (
    <div className="group grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-button px-2 py-2 transition-colors duration-150 hover:bg-surface sm:grid-cols-[2rem_auto_1fr_auto]">
      <span className="hidden text-center text-support text-fg-muted tabular-nums sm:block">
        {index != null ? index + 1 : null}
      </span>
      <button
        type="button"
        onClick={onPlay}
        aria-label={`Play ${track.title} by ${track.artist}`}
        className="relative size-12 shrink-0"
      >
        <TrackArtwork
          src={track.artworkUrl}
          seed={track.id}
          alt=""
          sizes="48px"
          className="size-12 rounded-button-sm"
        />
        <span className="absolute inset-0 grid place-items-center rounded-button-sm bg-black/50 opacity-0 transition-opacity group-hover:opacity-100">
          <Play className="size-4 fill-white text-white" />
        </span>
      </button>
      <div className="min-w-0">
        <Link
          href={`/tracks/${track.id}`}
          className="block truncate font-medium hover:underline"
        >
          {track.title}
        </Link>
        <p className="truncate text-support text-fg-secondary">
          {track.artistId ? (
            <Link href={`/artists/${track.artistId}`} className="hover:text-fg">
              {track.artist}
            </Link>
          ) : (
            track.artist
          )}
          {track.album ? (
            <span className="text-fg-muted"> · {track.album}</span>
          ) : null}
        </p>
        {showReason && track.reason ? (
          <p className="mt-0.5 truncate text-meta text-fg-muted">
            {track.reason}
          </p>
        ) : null}
      </div>
      <div className="flex items-center gap-1">
        {duration ? (
          <span className="hidden w-12 text-right text-support text-fg-muted tabular-nums md:block">
            {duration}
          </span>
        ) : null}
        {state ? (
          <FeedbackButtons
            trackId={track.id}
            title={track.title}
            state={state}
            requestId={track.requestId}
          />
        ) : null}
        {actions ?? <AddToPlaylist trackId={track.id} title={track.title} />}
      </div>
    </div>
  );
}

export function ArtistCard({
  id,
  name,
  detail,
  artworkUrl,
  selected,
  onSelect,
}: {
  id: string;
  name: string;
  detail?: string;
  artworkUrl?: string | null;
  selected?: boolean;
  onSelect?: () => void;
}) {
  const body = (
    <>
      <div className="relative">
        <TrackArtwork
          src={artworkUrl}
          seed={id}
          label={name}
          alt=""
          round
          sizes="160px"
        />
        {selected ? (
          <span className="absolute inset-0 grid place-items-center rounded-full bg-accent/25 ring-2 ring-accent">
            <span className="rounded-full bg-accent px-2 py-0.5 text-meta font-bold text-on-accent">
              Selected
            </span>
          </span>
        ) : null}
      </div>
      <div className="min-w-0 text-center">
        <p className="truncate font-display font-semibold">{name}</p>
        {detail ? (
          <p className="truncate text-meta text-fg-muted">{detail}</p>
        ) : null}
      </div>
    </>
  );
  const className =
    "flex w-full flex-col gap-3 rounded-card p-3 text-left transition-colors duration-200 hover:bg-surface";
  if (onSelect) {
    return (
      <motion.button
        {...hover}
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={className}
      >
        {body}
      </motion.button>
    );
  }
  return (
    <motion.div {...hover}>
      <Link href={`/artists/${id}`} className={className}>
        {body}
      </Link>
    </motion.div>
  );
}

export function PlaylistCard({
  id,
  name,
  detail,
  artworkUrls,
}: {
  id: string;
  name: string;
  detail: string;
  artworkUrls: string[];
}) {
  return (
    <motion.div {...hover}>
      <Link
        href={`/playlists/${id}`}
        className="flex flex-col gap-3 rounded-card bg-surface p-3 shadow-card transition-colors hover:bg-surface-hover"
      >
        <CollageArtwork urls={artworkUrls} seed={id} label={name} />
        <div className="min-w-0">
          <p className="truncate font-display font-semibold">{name}</p>
          <p className="truncate text-support text-fg-secondary">{detail}</p>
        </div>
      </Link>
    </motion.div>
  );
}

export function MoodCard({
  moodKey,
  title,
  description,
  className,
}: {
  moodKey: string;
  title: string;
  description: string;
  className?: string;
}) {
  return (
    <motion.div {...hover} className={className}>
      <Link
        href={`/moods/${moodKey}`}
        className="group relative flex aspect-[4/5] flex-col justify-end overflow-hidden rounded-card-lg p-4 shadow-card"
      >
        <div className="absolute inset-0">
          <GeneratedCover seed={`mood-${moodKey}`} />
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent" />
        <div className="relative">
          <p className="font-display text-section leading-tight font-bold">
            {title}
          </p>
          <p className="mt-1 line-clamp-2 text-support text-white/75">
            {description}
          </p>
        </div>
        <ArrowUpRight className="absolute top-4 right-4 size-5 text-white/70 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
      </Link>
    </motion.div>
  );
}

export function GenreCard({
  name,
  detail,
  href,
}: {
  name: string;
  detail?: string;
  href: string;
}) {
  return (
    <motion.div {...hover}>
      <Link
        href={href}
        className="relative flex h-24 items-end overflow-hidden rounded-card p-3 shadow-card"
      >
        <div className="absolute inset-0">
          <GeneratedCover seed={`genre-${name}`} />
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 to-transparent" />
        <div className="relative">
          <p className="font-display font-bold capitalize">{name}</p>
          {detail ? <p className="text-meta text-white/70">{detail}</p> : null}
        </div>
      </Link>
    </motion.div>
  );
}

export function SourceBadges({ sources }: { sources?: string[] }) {
  if (!sources?.length) return null;
  return (
    <div className="flex flex-wrap gap-1">
      {sources.map((source) => (
        <Pill key={source}>{sourceLabel(source)}</Pill>
      ))}
    </div>
  );
}
