"use client";

import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  ArrowLeft,
  GripVertical,
  ListMusic,
  MoreHorizontal,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Shuffle,
  Trash2,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageContainer, Section } from "@/components/layout/page";
import { CollageArtwork } from "@/components/music/artwork";
import { TrackRow } from "@/components/music/cards";
import {
  fromRecommendation,
  fromSummary,
  toQueue,
  type DisplayTrack,
} from "@/components/music/display";
import { RowsSkeleton, TrackRows } from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/primitives";
import {
  EmptyState,
  ErrorState,
  Skeleton,
  Spinner,
} from "@/components/ui/states";
import { useFeedbackStates } from "@/features/feedback/queries";
import { ApiError } from "@/services/api-client";
import { usePlayer } from "@/stores/player";
import type { PlaylistDetail } from "@/types/api";

import { EditPlaylistDialog } from "./playlist-dialogs";
import { playlistDetail } from "./playlists-page";
import {
  useAddToPlaylist,
  useDeletePlaylist,
  usePlaylist,
  usePlaylistSuggestions,
  useRegeneratePlaylist,
  useRemoveFromPlaylist,
  useReorderPlaylist,
} from "./queries";

const COLLECTION_LABELS: Record<string, string> = {
  for_you: "your mix",
  mood: "a mood",
  hidden_gems: "hidden gems",
  genre: "a genre",
  artist_radio: "an artist radio",
};

function SortableTrack({
  track,
  index,
  onPlay,
  onRemove,
  state,
}: {
  track: DisplayTrack;
  index: number;
  onPlay: () => void;
  onRemove: () => void;
  state: ReturnType<ReturnType<typeof useFeedbackStates>>;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: track.id });
  return (
    <li
      ref={setNodeRef}
      style={{ transform: CSS.Transform.toString(transform), transition }}
      className={
        isDragging
          ? "relative z-10 flex items-center rounded-button bg-surface-elevated shadow-elevated"
          : "flex items-center"
      }
    >
      <button
        type="button"
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        aria-label={`Move ${track.title}. Press space to pick up, arrows to move, space to drop.`}
        className="grid h-12 w-7 shrink-0 cursor-grab touch-none place-items-center rounded-button-sm text-fg-muted hover:text-fg active:cursor-grabbing"
      >
        <GripVertical className="size-4" />
      </button>
      <div className="min-w-0 flex-1">
        <TrackRow
          track={track}
          index={index}
          state={state}
          onPlay={onPlay}
          actions={
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={`Remove ${track.title} from playlist`}
              onClick={onRemove}
            >
              <X />
            </Button>
          }
        />
      </div>
    </li>
  );
}

function TrackList({ playlist }: { playlist: PlaylistDetail }) {
  const reorder = useReorderPlaylist(playlist.id);
  const remove = useRemoveFromPlaylist(playlist.id);
  const play = usePlayer((s) => s.play);
  const tracks = playlist.tracks.map(fromSummary);
  const stateOf = useFeedbackStates(tracks.map((t) => t.id));
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  );
  const titleOf = (id: unknown) =>
    tracks.find((t) => t.id === id)?.title ?? "track";

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const ids = tracks.map((t) => t.id);
    const next = arrayMove(
      ids,
      ids.indexOf(String(active.id)),
      ids.indexOf(String(over.id)),
    );
    reorder.mutate(next, {
      onError: () => toast.error("Could not save the new order"),
    });
  };

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={onDragEnd}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => `Picked up ${titleOf(active.id)}.`,
          onDragOver: ({ active, over }) =>
            over
              ? `${titleOf(active.id)} is over position ${tracks.findIndex((t) => t.id === over.id) + 1}.`
              : "",
          onDragEnd: ({ active, over }) =>
            over
              ? `Moved ${titleOf(active.id)} to position ${tracks.findIndex((t) => t.id === over.id) + 1}.`
              : "Move cancelled.",
          onDragCancel: ({ active }) =>
            `Move of ${titleOf(active.id)} cancelled.`,
        },
      }}
    >
      <SortableContext
        items={tracks.map((t) => t.id)}
        strategy={verticalListSortingStrategy}
      >
        <ol aria-label={`Tracks in ${playlist.name}`} className="flex flex-col">
          {tracks.map((track, i) => (
            <SortableTrack
              key={track.id}
              track={track}
              index={i}
              state={stateOf(track.id)}
              onPlay={() => play(tracks.map(toQueue), i)}
              onRemove={() =>
                remove.mutate(track.id, {
                  onSuccess: () => toast.success(`Removed ${track.title}`),
                  onError: (error) => toast.error(error.message),
                })
              }
            />
          ))}
        </ol>
      </SortableContext>
    </DndContext>
  );
}

function Suggestions({ playlist }: { playlist: PlaylistDetail }) {
  const suggestions = usePlaylistSuggestions(
    playlist.id,
    playlist.tracks.length > 0,
  );
  const add = useAddToPlaylist();
  const tracks =
    suggestions.data?.recommendations.map(fromRecommendation) ?? [];
  if (!tracks.length) return null;
  return (
    <Section
      title="Suggested for this playlist"
      description="Tracks that fit what is already here."
    >
      <TrackRows
        label="Suggested tracks"
        tracks={tracks}
        showReason
        actions={(track) => (
          <Button
            variant="secondary"
            size="sm"
            disabled={add.isPending}
            onClick={() =>
              add.mutate(
                { playlistId: playlist.id, trackIds: [track.id] },
                {
                  onSuccess: () => toast.success(`Added ${track.title}`),
                  onError: (error) => toast.error(error.message),
                },
              )
            }
          >
            <Plus /> Add
          </Button>
        )}
      />
    </Section>
  );
}

export function PlaylistDetailPage({ id }: { id: string }) {
  const router = useRouter();
  const playlist = usePlaylist(id);
  const regenerate = useRegeneratePlaylist(id);
  const remove = useDeletePlaylist();
  const play = usePlayer((s) => s.play);
  const playShuffled = usePlayer((s) => s.playShuffled);
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState<"delete" | "regenerate" | null>(null);

  if (playlist.isPending) {
    return (
      <PageContainer>
        <Skeleton className="h-48 rounded-card-lg" />
        <RowsSkeleton count={8} />
      </PageContainer>
    );
  }
  if (playlist.isError) {
    const missing =
      playlist.error instanceof ApiError && playlist.error.status === 404;
    return (
      <PageContainer>
        {missing ? (
          <EmptyState
            icon={ListMusic}
            title="Playlist not found"
            description="It may have been deleted."
            action={
              <Button asChild variant="secondary">
                <Link href="/playlists">Your playlists</Link>
              </Button>
            }
          />
        ) : (
          <ErrorState onRetry={() => void playlist.refetch()} />
        )}
      </PageContainer>
    );
  }

  const data = playlist.data;
  const queue = data.tracks.map(fromSummary).map(toQueue);
  const generatedFrom = data.collection
    ? COLLECTION_LABELS[data.collection]
    : null;

  return (
    <PageContainer>
      <Link
        href="/playlists"
        className="inline-flex w-fit items-center gap-1.5 text-support font-semibold text-fg-secondary hover:text-fg"
      >
        <ArrowLeft className="size-4" /> Playlists
      </Link>
      <section className="flex flex-col gap-6 sm:flex-row sm:items-end">
        <div className="w-40 shrink-0 sm:w-52">
          <CollageArtwork
            urls={data.artwork_urls}
            seed={data.id}
            label={data.name}
            className="shadow-elevated"
          />
        </div>
        <div className="min-w-0">
          <p className="text-meta font-semibold tracking-wider text-accent uppercase">
            {data.kind === "generated"
              ? `Playlist · generated from ${generatedFrom ?? "a mix"}`
              : "Playlist"}
          </p>
          <h1 className="mt-1 font-display text-hero leading-none font-bold break-words">
            {data.name}
          </h1>
          {data.description ? (
            <p className="mt-3 max-w-xl text-fg-secondary">
              {data.description}
            </p>
          ) : null}
          <p className="mt-2 text-support text-fg-muted">
            {playlistDetail(data)}
          </p>
        </div>
      </section>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="lg"
          onClick={() => play(queue, 0)}
          disabled={!queue.length}
        >
          <Play className="fill-current" /> Play
        </Button>
        <Button
          size="lg"
          variant="secondary"
          onClick={() => playShuffled(queue)}
          disabled={!queue.length}
        >
          <Shuffle /> Shuffle
        </Button>
        {data.kind === "generated" ? (
          <Button
            size="lg"
            variant="secondary"
            onClick={() => setConfirm("regenerate")}
            disabled={regenerate.isPending}
          >
            {regenerate.isPending ? <Spinner /> : <RefreshCw />} Regenerate
          </Button>
        ) : null}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              aria-label="More playlist actions"
            >
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => setEditing(true)}>
              <Pencil /> Edit details
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => setConfirm("delete")}
              className="text-error"
            >
              <Trash2 /> Delete playlist
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {data.tracks.length ? (
        <TrackList playlist={data} />
      ) : (
        <EmptyState
          icon={ListMusic}
          title="This playlist is empty"
          description="Add tracks from any card with the + button, or pick from the suggestions."
          action={
            <Button asChild variant="secondary">
              <Link href="/discover">Find music</Link>
            </Button>
          }
        />
      )}
      <Suggestions playlist={data} />

      <EditPlaylistDialog
        playlist={data}
        open={editing}
        onOpenChange={setEditing}
      />
      <Dialog
        open={confirm !== null}
        onOpenChange={(open) => !open && setConfirm(null)}
      >
        <DialogContent
          title={
            confirm === "delete"
              ? "Delete this playlist?"
              : "Regenerate this playlist?"
          }
          description={
            confirm === "delete"
              ? `"${data.name}" will be deleted for good. Your likes and listening history stay.`
              : "Its tracks are replaced with a fresh set from the same source, leaving out the current ones."
          }
        >
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            {confirm === "delete" ? (
              <Button
                variant="danger"
                disabled={remove.isPending}
                onClick={() =>
                  remove.mutate(data.id, {
                    onSuccess: () => {
                      toast.success(`Deleted "${data.name}"`);
                      router.replace("/playlists");
                    },
                    onError: (error) => toast.error(error.message),
                  })
                }
              >
                {remove.isPending ? <Spinner /> : <Trash2 />} Delete
              </Button>
            ) : (
              <Button
                onClick={() => {
                  setConfirm(null);
                  regenerate.mutate(undefined, {
                    onSuccess: () => toast.success("Fresh tracks added"),
                    onError: (error) => toast.error(error.message),
                  });
                }}
              >
                <RefreshCw /> Regenerate
              </Button>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </PageContainer>
  );
}
