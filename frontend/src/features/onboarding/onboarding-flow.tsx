"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Search, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useDeferredValue, useMemo, useState } from "react";
import { z } from "zod";

import { BrandLogo } from "@/components/layout/navigation";
import { ArtistCard } from "@/components/music/cards";
import { fromRecommendation } from "@/components/music/display";
import {
  CardsSkeleton,
  TrackCards,
} from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import { EmptyState, ErrorState, Pill, Spinner } from "@/components/ui/states";
import { useUpdateAccount } from "@/features/auth/queries";
import {
  useArtistSearch,
  useGenres,
  useMoods,
  usePopular,
} from "@/features/recommendations/queries";
import { ExplorationPicker } from "@/features/settings/exploration-picker";
import { useUpdatePreferences } from "@/features/taste-profile/queries";
import { cn } from "@/lib/utils";
import { recommendations } from "@/services/api";
import type { ExplorationMode } from "@/types/api";

/** Display name -> catalogue genre name (the tiles of step 2). */
export const FEATURED_GENRES: { label: string; genre: string }[] = [
  { label: "Indie", genre: "indie rock" },
  { label: "Alternative", genre: "alternative rock" },
  { label: "Hip-Hop", genre: "hip hop" },
  { label: "Electronic", genre: "electronic" },
  { label: "Pop", genre: "pop" },
  { label: "Rock", genre: "rock" },
  { label: "Jazz", genre: "jazz" },
  { label: "Classical", genre: "classical" },
  { label: "R&B", genre: "contemporary r&b" },
  { label: "Metal", genre: "metal" },
];

interface Artist {
  id: string;
  name: string;
}

const choicesSchema = z.object({
  genres: z.array(z.string()).max(30),
  artists: z.array(z.object({ id: z.string(), name: z.string() })).max(50),
  moods: z.array(z.string()).max(8),
  disliked: z.array(z.object({ id: z.string(), name: z.string() })).max(200),
  exploration: z.enum(["familiar", "balanced", "explorer"]).nullable(),
});
type Choices = z.infer<typeof choicesSchema>;

const STEPS = [
  "Welcome",
  "Genres",
  "Artists",
  "Preferences",
  "Exploration",
  "Your sound",
] as const;

function Progress({ step }: { step: number }) {
  return (
    <ol aria-label="Onboarding progress" className="flex gap-1.5">
      {STEPS.map((label, i) => (
        <li key={label} className="flex-1">
          <span className="sr-only">
            {label}
            {i < step ? " (done)" : i === step ? " (current)" : ""}
          </span>
          <span
            aria-hidden
            className={cn(
              "block h-1 rounded-full transition-colors duration-200",
              i <= step ? "bg-accent" : "bg-surface-hover",
            )}
          />
        </li>
      ))}
    </ol>
  );
}

function toggle<T>(
  list: T[],
  item: T,
  same: (a: T, b: T) => boolean = Object.is,
): T[] {
  return list.some((x) => same(x, item))
    ? list.filter((x) => !same(x, item))
    : [...list, item];
}

export function ArtistPicker({
  selected,
  onToggle,
  suggestions,
}: {
  selected: Artist[];
  onToggle: (artist: Artist) => void;
  suggestions: Artist[];
}) {
  const [query, setQuery] = useState("");
  const deferred = useDeferredValue(query);
  const search = useArtistSearch(deferred, 12);
  const results: Artist[] =
    deferred.trim().length >= 2
      ? (search.data?.results ?? []).map((a) => ({ id: a.id, name: a.name }))
      : suggestions;
  const details = new Map((search.data?.results ?? []).map((a) => [a.id, a]));
  return (
    <div className="flex flex-col gap-5">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-fg-muted" />
        <Input
          aria-label="Search artists"
          placeholder="Search artists"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="pl-10"
        />
      </div>
      {selected.length ? (
        <div className="flex flex-wrap gap-2" aria-label="Selected artists">
          {selected.map((artist) => (
            <button
              key={artist.id}
              type="button"
              onClick={() => onToggle(artist)}
              className="inline-flex items-center gap-1.5 rounded-full bg-accent-muted px-3 py-1 text-support font-semibold text-accent"
            >
              {artist.name}{" "}
              <X className="size-3.5" aria-label={`Remove ${artist.name}`} />
            </button>
          ))}
        </div>
      ) : null}
      {search.isFetching && deferred.trim().length >= 2 && !search.data ? (
        <div className="grid place-items-center py-10">
          <Spinner className="size-5" />
        </div>
      ) : results.length ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-6">
          {results.map((artist) => {
            const detail = details.get(artist.id);
            return (
              <ArtistCard
                key={artist.id}
                id={artist.id}
                name={artist.name}
                detail={detail?.genres.slice(0, 2).join(", ")}
                artworkUrl={detail?.artwork_url}
                selected={selected.some((a) => a.id === artist.id)}
                onSelect={() => onToggle(artist)}
              />
            );
          })}
        </div>
      ) : (
        <p className="py-6 text-center text-support text-fg-muted">
          {deferred.trim().length >= 2
            ? "No artists match that search."
            : "Search for artists you love."}
        </p>
      )}
    </div>
  );
}

export function OnboardingFlow() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [choices, setChoices] = useState<Choices>({
    genres: [],
    artists: [],
    moods: [],
    disliked: [],
    exploration: "balanced",
  });
  const genres = useGenres();
  const moods = useMoods();
  const popular = usePopular();
  const savePreferences = useUpdatePreferences();
  const updateAccount = useUpdateAccount();
  const firstMix = useMutation({
    mutationFn: () => recommendations.forYou(15),
  });

  const suggestedArtists = useMemo(() => {
    const seen = new Map<string, Artist>();
    for (const item of popular.data?.recommendations ?? []) {
      if (item.artist_id && !seen.has(item.artist_id)) {
        seen.set(item.artist_id, { id: item.artist_id, name: item.artist });
      }
    }
    return [...seen.values()].slice(0, 12);
  }, [popular.data]);

  const sameArtist = (a: Artist, b: Artist) => a.id === b.id;
  const extraGenres = (genres.data?.genres ?? [])
    .map((g) => g.name)
    .filter((name) => !FEATURED_GENRES.some((f) => f.genre === name))
    .slice(0, 24);

  async function finish() {
    const parsed = choicesSchema.parse(choices);
    await savePreferences.mutateAsync({
      exploration_mode: parsed.exploration as ExplorationMode | null,
      personalization_enabled: true,
      preferred_genres: parsed.genres,
      excluded_genres: [],
      preferred_artists: parsed.artists.map((a) => a.id),
      excluded_artists: parsed.disliked.map((a) => a.id),
      preferred_moods: parsed.moods,
    });
    firstMix.mutate();
  }

  const saving = savePreferences.isPending;
  const next = () => {
    if (step === 4) {
      setStep(5);
      void finish();
      return;
    }
    setStep((s) => Math.min(s + 1, STEPS.length - 1));
  };

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-4xl flex-col gap-8 px-4 py-6 sm:px-8">
      <div className="flex items-center justify-between gap-6">
        <BrandLogo />
        <div className="w-full max-w-xs">
          <Progress step={step} />
        </div>
      </div>
      <AnimatePresence mode="wait">
        <motion.section
          key={step}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.2 }}
          className="flex flex-1 flex-col gap-6"
          aria-labelledby="step-title"
        >
          {step === 0 ? (
            <div className="flex flex-1 flex-col justify-center gap-6 py-10">
              <h1 id="step-title" className="text-hero font-bold">
                Let&apos;s find <span className="text-accent">your sound.</span>
              </h1>
              <p className="max-w-xl text-lg text-fg-secondary">
                Tell SONIQUEO what you love and how adventurous you feel. It
                starts personalizing right away, and keeps learning from what
                you play, like and skip. You can change every answer later in
                Settings.
              </p>
            </div>
          ) : null}

          {step === 1 ? (
            <>
              <div>
                <h1 id="step-title" className="text-page font-bold">
                  Pick your genres
                </h1>
                <p className="mt-1 text-fg-secondary">
                  Choose as many as you like.
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
                {FEATURED_GENRES.map(({ label, genre }) => {
                  const active = choices.genres.includes(genre);
                  return (
                    <button
                      key={genre}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setChoices((c) => ({
                          ...c,
                          genres: toggle(c.genres, genre),
                        }))
                      }
                      className={cn(
                        "flex h-20 items-end justify-between rounded-card border p-3 text-left font-display text-card font-bold transition-all duration-150",
                        active
                          ? "border-accent bg-accent-muted text-accent"
                          : "border-border bg-surface hover:bg-surface-hover",
                      )}
                    >
                      {label}
                      {active ? <Check className="size-4" /> : null}
                    </button>
                  );
                })}
              </div>
              {extraGenres.length ? (
                <div>
                  <p className="mb-2 text-support font-semibold text-fg-secondary">
                    More genres
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {extraGenres.map((genre) => {
                      const active = choices.genres.includes(genre);
                      return (
                        <button
                          key={genre}
                          type="button"
                          aria-pressed={active}
                          onClick={() =>
                            setChoices((c) => ({
                              ...c,
                              genres: toggle(c.genres, genre),
                            }))
                          }
                        >
                          <Pill
                            active={active}
                            className="px-3 py-1 text-support capitalize"
                          >
                            {genre}
                          </Pill>
                        </button>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </>
          ) : null}

          {step === 2 ? (
            <>
              <div>
                <h1 id="step-title" className="text-page font-bold">
                  Artists you love
                </h1>
                <p className="mt-1 text-fg-secondary">
                  They anchor your first recommendations.
                </p>
              </div>
              <ArtistPicker
                selected={choices.artists}
                suggestions={suggestedArtists}
                onToggle={(artist) =>
                  setChoices((c) => ({
                    ...c,
                    artists: toggle(c.artists, artist, sameArtist),
                  }))
                }
              />
            </>
          ) : null}

          {step === 3 ? (
            <>
              <div>
                <h1 id="step-title" className="text-page font-bold">
                  Moods and no-gos
                </h1>
                <p className="mt-1 text-fg-secondary">
                  Favourite moods come first on your home page. Artists you
                  exclude never appear.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {(moods.data?.moods ?? []).map((mood) => {
                  const active = choices.moods.includes(mood.key);
                  return (
                    <button
                      key={mood.key}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setChoices((c) => ({
                          ...c,
                          moods: toggle(c.moods, mood.key),
                        }))
                      }
                    >
                      <Pill
                        active={active}
                        className="px-3.5 py-1.5 text-support"
                      >
                        {mood.title}
                      </Pill>
                    </button>
                  );
                })}
              </div>
              <div>
                <p className="mb-3 font-display text-card font-semibold">
                  Artists to exclude (optional)
                </p>
                <ArtistPicker
                  selected={choices.disliked}
                  suggestions={[]}
                  onToggle={(artist) =>
                    setChoices((c) => ({
                      ...c,
                      disliked: toggle(c.disliked, artist, sameArtist),
                    }))
                  }
                />
              </div>
            </>
          ) : null}

          {step === 4 ? (
            <>
              <div>
                <h1 id="step-title" className="text-page font-bold">
                  How adventurous are you?
                </h1>
                <p className="mt-1 text-fg-secondary">
                  This sets the share of new artists in your mixes. You can
                  change it any time.
                </p>
              </div>
              <ExplorationPicker
                value={choices.exploration}
                onChange={(exploration) =>
                  setChoices((c) => ({ ...c, exploration }))
                }
              />
            </>
          ) : null}

          {step === 5 ? (
            <>
              <div>
                <h1 id="step-title" className="text-page font-bold">
                  Your first mix
                </h1>
                <p className="mt-1 text-fg-secondary">
                  Built from your answers. It sharpens as you listen, like and
                  skip.
                </p>
              </div>
              {savePreferences.isError ? (
                <ErrorState
                  message={savePreferences.error.message}
                  onRetry={() => void finish()}
                />
              ) : firstMix.isError ? (
                <ErrorState
                  message="Could not build your first mix."
                  onRetry={() => firstMix.mutate()}
                />
              ) : firstMix.data ? (
                firstMix.data.recommendations.length ? (
                  <TrackCards
                    label="Your first recommendations"
                    tracks={firstMix.data.recommendations.map((item) =>
                      fromRecommendation(item, firstMix.data.request_id),
                    )}
                  />
                ) : (
                  <EmptyState
                    title="No recommendations yet"
                    description="Pick a few genres or artists so SONIQUEO has something to go on."
                  />
                )
              ) : (
                <CardsSkeleton count={10} />
              )}
            </>
          ) : null}
        </motion.section>
      </AnimatePresence>

      <div className="sticky bottom-0 flex items-center justify-between gap-3 border-t border-border bg-background/95 py-4 backdrop-blur">
        <Button
          variant="ghost"
          onClick={() => setStep((s) => Math.max(s - 1, 0))}
          disabled={step === 0 || step === 5}
        >
          <ArrowLeft /> Back
        </Button>
        {step < 5 ? (
          <Button onClick={next} disabled={saving} size="lg">
            {step === 0
              ? "Get started"
              : step === 4
                ? "Build my mix"
                : "Continue"}{" "}
            <ArrowRight />
          </Button>
        ) : (
          <Button
            size="lg"
            disabled={!firstMix.data || updateAccount.isPending}
            onClick={() =>
              updateAccount.mutate(
                { onboarding_completed: true },
                { onSuccess: () => router.replace("/home") },
              )
            }
          >
            {updateAccount.isPending ? <Spinner /> : null} Go to my home
          </Button>
        )}
      </div>
    </div>
  );
}
