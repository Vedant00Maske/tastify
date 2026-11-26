"use client";

import {
  ExternalLink,
  ListMusic,
  Shuffle,
  SkipBack,
  SkipForward,
  X,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useState } from "react";

import { TrackArtwork } from "@/components/music/artwork";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { currentTrack, listenLinks, usePlayer } from "@/stores/player";

/**
 * The persistent player bar. SONIQUEO does not play audio yet, and this bar says so plainly: it
 * holds the queue and offers "listen on" links, and it never fakes progress or records plays.
 */
export function MusicPlayer() {
  const state = usePlayer();
  const track = currentTrack(state);
  const [queueOpen, setQueueOpen] = useState(false);
  if (!track) return null;
  const links = listenLinks(track);
  return (
    <div
      role="region"
      aria-label="Player"
      className="fixed inset-x-0 bottom-14 z-40 border-t border-border bg-background-secondary/95 backdrop-blur lg:bottom-0"
    >
      <AnimatePresence>
        {queueOpen ? (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={{ duration: 0.2 }}
            className="absolute right-2 bottom-full mb-2 max-h-80 w-[min(22rem,calc(100vw-1rem))] overflow-y-auto rounded-card border border-border bg-surface-elevated p-2 shadow-elevated"
          >
            <p className="px-2 py-1 text-meta font-semibold text-fg-muted">
              Queue
            </p>
            <ol>
              {state.queue.map((item, i) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => state.jump(i)}
                    aria-current={i === state.index ? "true" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-button-sm px-2 py-1.5 text-left text-sm hover:bg-surface-hover",
                      i === state.index && "text-accent",
                    )}
                  >
                    <span className="w-5 text-meta text-fg-muted tabular-nums">
                      {i + 1}
                    </span>
                    <span className="truncate">
                      {item.title}{" "}
                      <span className="text-fg-muted">· {item.artist}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </motion.div>
        ) : null}
      </AnimatePresence>
      <div className="mx-auto flex h-18 max-w-[1440px] items-center gap-3 px-3 sm:px-6">
        <TrackArtwork
          src={track.artworkUrl}
          seed={track.id}
          label={track.artist}
          alt=""
          sizes="48px"
          className="size-12 shrink-0 rounded-button-sm shadow-glow"
        />
        <div className="min-w-0 flex-1 sm:flex-none sm:basis-64">
          <Link
            href={`/tracks/${track.id}`}
            className="block truncate font-semibold hover:underline"
          >
            {track.title}
          </Link>
          <p className="truncate text-support text-fg-secondary">
            {track.artist}
          </p>
        </div>
        <div className="flex items-center gap-1 sm:mx-auto">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Previous in queue"
            disabled={state.index === 0}
            onClick={state.previous}
          >
            <SkipBack />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Next in queue"
            disabled={state.index >= state.queue.length - 1}
            onClick={state.next}
          >
            <SkipForward />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Shuffle queue"
            className="hidden sm:inline-flex"
            onClick={state.shuffle}
          >
            <Shuffle />
          </Button>
        </div>
        <div className="hidden items-center gap-2 md:flex">
          <span className="text-meta text-fg-muted">
            SONIQUEO does not play audio yet. Listen on
          </span>
          {links.map((link) => (
            <a
              key={link.label}
              href={link.href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-meta font-semibold text-fg-secondary hover:border-fg-muted hover:text-fg"
            >
              {link.label} <ExternalLink className="size-3" />
            </a>
          ))}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={queueOpen ? "Hide queue" : "Show queue"}
          aria-expanded={queueOpen}
          onClick={() => setQueueOpen((open) => !open)}
        >
          <ListMusic />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Close player"
          onClick={state.clear}
        >
          <X />
        </Button>
      </div>
    </div>
  );
}
