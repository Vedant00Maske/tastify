"use client";

import {
  Bookmark,
  BookmarkCheck,
  Heart,
  ListPlus,
  Plus,
  ThumbsDown,
} from "lucide-react";
import { motion } from "motion/react";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/primitives";
import { useFeedback } from "@/features/feedback/queries";
import { useAddToPlaylist, usePlaylists } from "@/features/playlists/queries";
import { cn } from "@/lib/utils";
import type { FeedbackState } from "@/types/api";

function Toggle({
  label,
  active,
  onClick,
  children,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      aria-label={label}
      aria-pressed={active}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className={cn(active && "text-accent hover:text-accent-hover")}
    >
      <motion.span
        key={String(active)}
        initial={{ scale: 0.7 }}
        animate={{ scale: 1 }}
        transition={{ duration: 0.15 }}
        className="flex"
      >
        {children}
      </motion.span>
    </Button>
  );
}

/** Like, dislike and save: explicit feedback that the backend turns into taste signals. */
export function FeedbackButtons({
  trackId,
  title,
  state,
}: {
  trackId: string;
  title: string;
  state: FeedbackState;
}) {
  const feedback = useFeedback();
  const send = (
    eventType: Parameters<typeof feedback.mutate>[0]["eventType"],
    message?: string,
  ) =>
    feedback.mutate(
      { trackId, eventType },
      {
        onSuccess: () => {
          if (message) toast(message);
        },
        onError: () => toast.error("That did not save. Try again."),
      },
    );
  return (
    <div className="flex items-center">
      <Toggle
        label={state.liked ? `Unlike ${title}` : `Like ${title}`}
        active={state.liked}
        onClick={() => send(state.liked ? "unlike" : "like")}
      >
        <Heart className={cn(state.liked && "fill-current")} />
      </Toggle>
      <Toggle
        label={
          state.disliked ? `Remove dislike of ${title}` : `Dislike ${title}`
        }
        active={state.disliked}
        onClick={() =>
          send(
            state.disliked ? "undislike" : "dislike",
            state.disliked
              ? undefined
              : "Got it. You will hear less like this.",
          )
        }
      >
        <ThumbsDown className={cn(state.disliked && "fill-current")} />
      </Toggle>
      <Toggle
        label={state.saved ? `Remove ${title} from saved` : `Save ${title}`}
        active={state.saved}
        onClick={() =>
          send(
            state.saved ? "unsave" : "save",
            state.saved ? undefined : "Saved",
          )
        }
      >
        {state.saved ? <BookmarkCheck /> : <Bookmark />}
      </Toggle>
    </div>
  );
}

/** "Add to playlist" menu: existing playlists, or a link to create one. */
export function AddToPlaylist({
  trackId,
  title,
}: {
  trackId: string;
  title: string;
}) {
  const playlists = usePlaylists();
  const add = useAddToPlaylist();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={`Add ${title} to a playlist`}
          onClick={(event) => event.stopPropagation()}
        >
          <ListPlus />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent onClick={(event) => event.stopPropagation()}>
        <DropdownMenuLabel>Add to playlist</DropdownMenuLabel>
        {playlists.data?.playlists.length ? (
          playlists.data.playlists.slice(0, 12).map((playlist) => (
            <DropdownMenuItem
              key={playlist.id}
              onSelect={() =>
                add.mutate(
                  { playlistId: playlist.id, trackIds: [trackId] },
                  {
                    onSuccess: () => toast(`Added to ${playlist.name}`),
                    onError: () => toast.error("Could not add the track"),
                  },
                )
              }
            >
              <span className="truncate">{playlist.name}</span>
            </DropdownMenuItem>
          ))
        ) : (
          <p className="px-2.5 py-2 text-support text-fg-muted">
            {playlists.isLoading ? "Loading playlists…" : "No playlists yet."}
          </p>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/playlists?new=1">
            <Plus /> New playlist
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
