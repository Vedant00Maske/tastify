"use client";

import { useMutation } from "@tanstack/react-query";
import { ListPlus, Play, RefreshCw, Sparkles, Wand2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageContainer, PageHeading } from "@/components/layout/page";
import { fromRecommendation, toQueue } from "@/components/music/display";
import { RowsSkeleton, TrackRows } from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import { Label, Textarea } from "@/components/ui/form";
import { Switch } from "@/components/ui/primitives";
import { EmptyState, Pill, Spinner } from "@/components/ui/states";
import { useCreatePlaylist } from "@/features/playlists/queries";
import { useMoods } from "@/features/recommendations/queries";
import { cn } from "@/lib/utils";
import { recommendations } from "@/services/api";
import { ApiError } from "@/services/api-client";
import { usePlayer } from "@/stores/player";
import type { CustomRequest, Interpretation } from "@/types/api";

export const EXAMPLES = [
  "Indie rock with electronic influence",
  "Chill 90s hip hop, no metal",
  "Something like Radiohead but more upbeat",
  "Hidden gems of dream pop for a rainy afternoon",
  "Fast synth-pop around 128 bpm, new artists",
];

const FAMILIARITY: { label: string; value: number | null }[] = [
  { label: "From my prompt", value: null },
  { label: "Familiar", value: 0.2 },
  { label: "Balanced", value: 0.5 },
  { label: "New to me", value: 0.8 },
];

function bounds(
  [low, high]: [number | null, number | null],
  unit: string,
  format = (v: number) => String(Math.round(v)),
): string | null {
  if (low != null && high != null)
    return `${format(low)}–${format(high)}${unit}`;
  if (low != null) return `over ${format(low)}${unit}`;
  if (high != null) return `under ${format(high)}${unit}`;
  return null;
}

function Understood({ interpretation }: { interpretation: Interpretation }) {
  const moods = useMoods();
  const title = (key: string) =>
    moods.data?.moods.find((m) => m.key === key)?.title ?? key;
  const chips: { key: string; node: React.ReactNode; excluded?: boolean }[] = [
    ...interpretation.genres.map((g) => ({
      key: `g-${g}`,
      node: <span className="capitalize">{g}</span>,
    })),
    ...interpretation.moods.map((m) => ({
      key: `m-${m}`,
      node: `${title(m)} mood`,
    })),
    ...interpretation.artists.map((a) => ({
      key: `a-${a.id}`,
      node: (
        <Link href={`/artists/${a.id}`} className="hover:underline">
          like {a.name}
        </Link>
      ),
    })),
  ];
  const constraints = [
    bounds(interpretation.tempo, " BPM"),
    interpretation.danceability[0] != null
      ? "danceable"
      : interpretation.danceability[1] != null
        ? "calm"
        : null,
    bounds(interpretation.years, "", (v) => String(v)),
    interpretation.popularity === "lesser_known"
      ? "lesser-known"
      : interpretation.popularity === "popular"
        ? "popular"
        : null,
    interpretation.exploration_level == null
      ? null
      : interpretation.exploration_level >= 0.5
        ? "mostly new artists"
        : "mostly familiar artists",
  ].filter((c): c is string => !!c);
  const excluded = [
    ...interpretation.excluded_genres,
    ...interpretation.excluded_artists.map((a) => a.name),
  ];
  return (
    <section
      aria-labelledby="understood-title"
      className="rounded-card-lg border border-border bg-surface p-4"
    >
      <h2
        id="understood-title"
        className="text-support font-semibold text-fg-secondary"
      >
        What SONIQUEO understood
      </h2>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <Pill key={chip.key} active className="px-2.5 py-1 text-support">
            {chip.node}
          </Pill>
        ))}
        {constraints.map((c) => (
          <Pill key={c} className="px-2.5 py-1 text-support">
            {c}
          </Pill>
        ))}
        {excluded.map((x) => (
          <Pill
            key={`x-${x}`}
            className="border-error/40 px-2.5 py-1 text-support text-error capitalize"
          >
            no {x}
          </Pill>
        ))}
      </div>
      {interpretation.ignored.length ? (
        <p className="mt-2 text-meta text-fg-muted">
          Not used: {interpretation.ignored.join(", ")}
        </p>
      ) : null}
    </section>
  );
}

function promptError(error: unknown): { message: string; ignored: string[] } {
  if (error instanceof ApiError && error.status === 422) {
    const detail = error.detail as { ignored?: string[] } | undefined;
    return { message: error.message, ignored: detail?.ignored ?? [] };
  }
  return {
    message:
      error instanceof ApiError
        ? error.message
        : "Could not reach SONIQUEO. Try again.",
    ignored: [],
  };
}

export function CreatePage() {
  const router = useRouter();
  const [prompt, setPrompt] = useState("");
  const [familiarity, setFamiliarity] = useState<number | null>(null);
  const [freshOnly, setFreshOnly] = useState(true);
  const [shown, setShown] = useState<string[]>([]);
  const [request, setRequest] = useState<CustomRequest | null>(null);
  const generate = useMutation({ mutationFn: recommendations.custom });
  const save = useCreatePlaylist();
  const playQueue = usePlayer((state) => state.play);

  const run = (body: CustomRequest) => {
    setRequest(body);
    generate.mutate(body, {
      onSuccess: (result) =>
        setShown((ids) => [
          ...ids,
          ...result.recommendations.map((r) => r.track_id),
        ]),
    });
  };
  const submit = () => {
    const clean = prompt.trim();
    if (clean.length < 2) return;
    setShown([]);
    run({
      prompt: clean,
      limit: 25,
      exploration_level: familiarity,
      exclude_previously_heard: freshOnly,
    });
  };

  const result = generate.data;
  const tracks =
    result?.recommendations.map((item) =>
      fromRecommendation(item, result.request_id),
    ) ?? [];

  return (
    <PageContainer>
      <PageHeading
        title="Create with words"
        description="Describe the playlist you want: genres, moods, artists it should sound like, tempo, era, or what to leave out."
      />
      <form
        className="flex flex-col gap-4 rounded-card-lg border border-border bg-surface p-4 sm:p-5"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="prompt">Describe your playlist</Label>
          <Textarea
            id="prompt"
            value={prompt}
            maxLength={300}
            placeholder="e.g. Indie rock with electronic influence, nothing too popular"
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey))
                submit();
            }}
            className="min-h-20"
          />
        </div>
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label="Examples"
        >
          {EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              onClick={() => setPrompt(example)}
            >
              <Pill className="px-2.5 py-1 text-support hover:text-fg">
                {example}
              </Pill>
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div
            className="flex flex-wrap items-center gap-1.5"
            role="group"
            aria-label="Familiarity"
          >
            {FAMILIARITY.map((option) => (
              <button
                key={option.label}
                type="button"
                aria-pressed={familiarity === option.value}
                onClick={() => setFamiliarity(option.value)}
                className={cn(
                  "rounded-full px-3 py-1 text-support font-semibold transition-colors",
                  familiarity === option.value
                    ? "bg-fg text-background"
                    : "bg-background-secondary text-fg-secondary hover:text-fg",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <label
            htmlFor="fresh-only"
            className="flex items-center gap-2 text-support text-fg-secondary"
          >
            <Switch
              id="fresh-only"
              checked={freshOnly}
              onCheckedChange={setFreshOnly}
            />
            Leave out tracks I have heard
          </label>
        </div>
        <div>
          <Button
            type="submit"
            size="lg"
            disabled={prompt.trim().length < 2 || generate.isPending}
          >
            {generate.isPending ? <Spinner /> : <Wand2 />} Create playlist
          </Button>
        </div>
      </form>

      {generate.isError ? (
        <div
          role="alert"
          className="rounded-card-lg border border-warning/40 bg-warning/5 p-4"
        >
          <p className="font-semibold">{promptError(generate.error).message}</p>
          {promptError(generate.error).ignored.length ? (
            <p className="mt-1 text-support text-fg-secondary">
              Not recognised: {promptError(generate.error).ignored.join(", ")}
            </p>
          ) : null}
        </div>
      ) : null}

      {generate.isPending && !result ? <RowsSkeleton count={8} /> : null}

      {result ? (
        <div className="flex flex-col gap-4">
          <Understood interpretation={result.interpretation} />
          <div className="flex flex-wrap gap-2">
            <Button
              size="lg"
              disabled={!tracks.length}
              onClick={() => playQueue(tracks.map(toQueue))}
            >
              <Play className="fill-current" /> Play
            </Button>
            <Button
              size="lg"
              variant="secondary"
              disabled={!request || generate.isPending}
              onClick={() =>
                request && run({ ...request, exclude: shown.slice(-100) })
              }
            >
              <RefreshCw /> Regenerate
            </Button>
            <Button
              size="lg"
              variant="outline"
              disabled={!tracks.length || save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    name: result.prompt.slice(0, 120),
                    description: `Made from the prompt "${result.prompt}".`,
                    track_ids: tracks.map((t) => t.id),
                    generator: {
                      collection: "custom",
                      prompt: result.prompt,
                      exploration_level: request?.exploration_level ?? null,
                      size: 25,
                    },
                  },
                  {
                    onSuccess: (playlist) =>
                      toast.success(`Saved "${playlist.name}"`, {
                        action: {
                          label: "Open",
                          onClick: () =>
                            router.push(`/playlists/${playlist.id}`),
                        },
                      }),
                    onError: (error) => toast.error(error.message),
                  },
                )
              }
            >
              {save.isPending ? <Spinner /> : <ListPlus />} Save as playlist
            </Button>
          </div>
          {tracks.length ? (
            <TrackRows
              label={`Playlist for ${result.prompt}`}
              tracks={tracks}
              showReason
            />
          ) : (
            <EmptyState
              icon={Sparkles}
              title="Nothing matches all of that"
              description="Try fewer constraints, a wider era, or allow tracks you have heard."
            />
          )}
        </div>
      ) : null}
    </PageContainer>
  );
}
