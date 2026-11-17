"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Dialog, DialogContent } from "@/components/ui/primitives";
import { Pill, Spinner } from "@/components/ui/states";
import { useMoods } from "@/features/recommendations/queries";
import { cn } from "@/lib/utils";
import type { Generator, PlaylistDetail } from "@/types/api";

import { useCreatePlaylist, useUpdatePlaylist } from "./queries";

export const playlistSchema = z.object({
  name: z
    .string()
    .trim()
    .min(1, "Give the playlist a name")
    .max(120, "Use at most 120 characters"),
  description: z.string().max(500, "Use at most 500 characters"),
});
type PlaylistValues = z.infer<typeof playlistSchema>;

type Start = "empty" | "for_you" | "hidden_gems" | "mood";
const STARTS: { key: Start; label: string; detail: string }[] = [
  { key: "empty", label: "Empty", detail: "Add tracks yourself" },
  { key: "for_you", label: "For you", detail: "Your personal mix" },
  { key: "hidden_gems", label: "Hidden gems", detail: "Lesser-known fits" },
  { key: "mood", label: "A mood", detail: "Pick a mood mix" },
];
const SIZES = [10, 25, 50];

export function CreatePlaylistDialog({
  open,
  onOpenChange,
  initialTrackIds = [],
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialTrackIds?: string[];
}) {
  const router = useRouter();
  const create = useCreatePlaylist();
  const moods = useMoods();
  const [start, setStart] = useState<Start>("empty");
  const [mood, setMood] = useState<string | null>(null);
  const [size, setSize] = useState(25);
  const form = useForm<PlaylistValues>({
    resolver: zodResolver(playlistSchema),
    defaultValues: { name: "", description: "" },
  });
  const { errors } = form.formState;
  const moodMissing = start === "mood" && !mood;

  const submit = form.handleSubmit(({ name, description }) => {
    if (moodMissing) return;
    const generator: Generator | undefined =
      start === "empty"
        ? undefined
        : start === "mood"
          ? { collection: "mood", mood: mood ?? undefined, size }
          : { collection: start, size };
    create.mutate(
      {
        name,
        description: description.trim() || null,
        track_ids: initialTrackIds,
        generator,
      },
      {
        onSuccess: (playlist) => {
          onOpenChange(false);
          form.reset();
          toast.success(`Created "${playlist.name}"`);
          router.push(`/playlists/${playlist.id}`);
        },
        onError: (error) => toast.error(error.message),
      },
    );
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title="New playlist"
        description="Start empty, or let TASTIFY fill it for you."
        className="max-w-lg"
      >
        <form noValidate onSubmit={submit} className="flex flex-col gap-4">
          <Field id="playlist-name" label="Name" error={errors.name?.message}>
            <Input
              id="playlist-name"
              autoFocus
              aria-invalid={!!errors.name}
              {...form.register("name")}
            />
          </Field>
          <Field
            id="playlist-description"
            label="Description (optional)"
            error={errors.description?.message}
          >
            <Textarea
              id="playlist-description"
              className="min-h-16"
              {...form.register("description")}
            />
          </Field>
          {initialTrackIds.length === 0 ? (
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-support font-semibold">
                Start from
              </legend>
              <div className="grid grid-cols-2 gap-2">
                {STARTS.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    aria-pressed={start === option.key}
                    onClick={() => setStart(option.key)}
                    className={cn(
                      "rounded-button border p-3 text-left transition-colors",
                      start === option.key
                        ? "border-accent bg-accent-muted"
                        : "border-border bg-background-secondary hover:bg-surface-hover",
                    )}
                  >
                    <span className="block text-support font-semibold">
                      {option.label}
                    </span>
                    <span className="block text-meta text-fg-muted">
                      {option.detail}
                    </span>
                  </button>
                ))}
              </div>
              {start === "mood" ? (
                <div
                  className="flex flex-wrap gap-1.5 pt-1"
                  role="group"
                  aria-label="Mood"
                >
                  {(moods.data?.moods ?? []).map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      aria-pressed={mood === m.key}
                      onClick={() => setMood(m.key)}
                    >
                      <Pill
                        active={mood === m.key}
                        className="px-3 py-1 text-support"
                      >
                        {m.title}
                      </Pill>
                    </button>
                  ))}
                </div>
              ) : null}
              {start !== "empty" ? (
                <div
                  className="flex items-center gap-2 pt-1"
                  role="group"
                  aria-label="Number of tracks"
                >
                  <span className="text-support text-fg-secondary">
                    Tracks:
                  </span>
                  {SIZES.map((n) => (
                    <button
                      key={n}
                      type="button"
                      aria-pressed={size === n}
                      onClick={() => setSize(n)}
                    >
                      <Pill
                        active={size === n}
                        className="px-3 py-1 text-support"
                      >
                        {n}
                      </Pill>
                    </button>
                  ))}
                </div>
              ) : null}
              {moodMissing && form.formState.isSubmitted ? (
                <p role="alert" className="text-support text-error">
                  Pick a mood.
                </p>
              ) : null}
            </fieldset>
          ) : null}
          <div className="mt-2 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? <Spinner /> : null} Create
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function EditPlaylistDialog({
  playlist,
  open,
  onOpenChange,
}: {
  playlist: PlaylistDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const update = useUpdatePlaylist(playlist.id);
  const form = useForm<PlaylistValues>({
    resolver: zodResolver(playlistSchema),
    values: { name: playlist.name, description: playlist.description ?? "" },
  });
  const { errors } = form.formState;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Edit playlist">
        <form
          noValidate
          className="flex flex-col gap-4"
          onSubmit={form.handleSubmit(({ name, description }) =>
            update.mutate(
              { name, description: description.trim() || null },
              {
                onSuccess: () => {
                  onOpenChange(false);
                  toast.success("Playlist updated");
                },
                onError: (error) => toast.error(error.message),
              },
            ),
          )}
        >
          <Field id="edit-name" label="Name" error={errors.name?.message}>
            <Input
              id="edit-name"
              aria-invalid={!!errors.name}
              {...form.register("name")}
            />
          </Field>
          <Field
            id="edit-description"
            label="Description"
            error={errors.description?.message}
          >
            <Textarea id="edit-description" {...form.register("description")} />
          </Field>
          <div className="mt-2 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? <Spinner /> : null} Save
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
