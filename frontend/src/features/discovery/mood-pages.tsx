"use client";

import { ArrowLeft, ListPlus, Play, RefreshCw, Shuffle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { PageContainer, PageHeading } from "@/components/layout/page";
import { GeneratedCover } from "@/components/music/artwork";
import { MoodCard } from "@/components/music/cards";
import { fromRecommendation, toQueue } from "@/components/music/display";
import { RowsSkeleton, TrackRows } from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorState,
  Pill,
  Skeleton,
  Spinner,
} from "@/components/ui/states";
import { useCreatePlaylist } from "@/features/playlists/queries";
import { useMoodMix, useMoods } from "@/features/recommendations/queries";
import { usePreferences } from "@/features/taste-profile/queries";
import { ApiError } from "@/services/api-client";
import { usePlayer } from "@/stores/player";

export function MoodsPage() {
  const moods = useMoods();
  const preferences = usePreferences();
  const favourite = new Set(preferences.data?.preferred_moods ?? []);
  return (
    <PageContainer>
      <PageHeading
        title="Mood Mix"
        description="Mixes built from genre, tempo and energy, tuned to your taste when you are signed in."
      />
      {moods.isPending ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="aspect-[4/5] rounded-card-lg" />
          ))}
        </div>
      ) : moods.isError ? (
        <ErrorState onRetry={() => void moods.refetch()} />
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
          {moods.data.moods.map((mood) => (
            <div key={mood.key} className="relative">
              <MoodCard
                moodKey={mood.key}
                title={mood.title}
                description={mood.description}
              />
              {favourite.has(mood.key) ? (
                <Pill
                  active
                  className="pointer-events-none absolute top-3 left-3 bg-background/80 backdrop-blur"
                >
                  Favourite
                </Pill>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </PageContainer>
  );
}

const MIX_SIZE = 25;

export function MoodDetailPage({ moodKey }: { moodKey: string }) {
  const router = useRouter();
  // Each regenerate leaves out every track shown so far (capped by the API at 100).
  const [round, setRound] = useState(0);
  const [shown, setShown] = useState<string[]>([]);
  const mix = useMoodMix(moodKey, MIX_SIZE, round, shown.slice(-100));
  const create = useCreatePlaylist();
  const play = usePlayer((s) => s.play);
  const playShuffled = usePlayer((s) => s.playShuffled);

  if (mix.isError) {
    return (
      <PageContainer>
        <BackToMoods />
        {mix.error instanceof ApiError && mix.error.status === 404 ? (
          <EmptyState
            title="No such mood"
            description="This mood mix does not exist."
          />
        ) : (
          <ErrorState onRetry={() => void mix.refetch()} />
        )}
      </PageContainer>
    );
  }
  if (!mix.data) {
    return (
      <PageContainer>
        <BackToMoods />
        <Skeleton className="h-48 rounded-card-lg" />
        <RowsSkeleton count={10} />
      </PageContainer>
    );
  }

  const { mood, personalized } = mix.data;
  const tracks = mix.data.recommendations.map(fromRecommendation);
  const queue = tracks.map(toQueue);

  const regenerate = () => {
    setShown((ids) => [...ids, ...tracks.map((t) => t.id)]);
    setRound((r) => r + 1);
  };

  const save = () =>
    create.mutate(
      {
        name: mood.title,
        description: mood.description,
        track_ids: tracks.map((t) => t.id),
        generator: { collection: "mood", mood: mood.key, size: MIX_SIZE },
      },
      {
        onSuccess: (playlist) =>
          toast.success(`Saved "${playlist.name}"`, {
            action: {
              label: "Open",
              onClick: () => router.push(`/playlists/${playlist.id}`),
            },
          }),
        onError: (error) => toast.error(error.message),
      },
    );

  return (
    <PageContainer>
      <BackToMoods />
      <section className="flex flex-col gap-6 sm:flex-row sm:items-end">
        <div className="w-40 shrink-0 overflow-hidden rounded-card-lg shadow-elevated sm:w-52">
          <div className="aspect-square">
            <GeneratedCover seed={`mood-${mood.key}`} />
          </div>
        </div>
        <div className="min-w-0">
          <p className="text-meta font-semibold tracking-wider text-accent uppercase">
            Mood mix{personalized ? " · tuned to you" : ""}
          </p>
          <h1 className="mt-1 font-display text-hero leading-none font-bold">
            {mood.title}
          </h1>
          <p className="mt-3 max-w-xl text-fg-secondary">{mood.description}</p>
          <div className="mt-2 flex flex-wrap gap-1">
            {mood.genres.slice(0, 6).map((genre) => (
              <Pill key={genre} className="capitalize">
                {genre}
              </Pill>
            ))}
          </div>
        </div>
      </section>
      <div className="flex flex-wrap gap-2">
        <Button
          size="lg"
          onClick={() => play(queue, 0)}
          disabled={!tracks.length}
        >
          <Play className="fill-current" /> Play
        </Button>
        <Button
          size="lg"
          variant="secondary"
          onClick={() => playShuffled(queue)}
          disabled={!tracks.length}
        >
          <Shuffle /> Shuffle
        </Button>
        <Button
          size="lg"
          variant="secondary"
          onClick={regenerate}
          disabled={mix.isFetching}
        >
          {mix.isFetching ? <Spinner /> : <RefreshCw />} Regenerate
        </Button>
        <Button
          size="lg"
          variant="outline"
          onClick={save}
          disabled={!tracks.length || create.isPending}
        >
          {create.isPending ? <Spinner /> : <ListPlus />} Save as playlist
        </Button>
      </div>
      {tracks.length ? (
        <TrackRows label={`${mood.title} mix`} tracks={tracks} showReason />
      ) : (
        <EmptyState
          title={round ? "That is everything for now" : "This mood is empty"}
          description={
            round
              ? "You have seen every track that fits this mood. Start over for the best matches."
              : "No tracks in the catalogue fit this mood yet."
          }
          action={
            round ? (
              <Button
                variant="secondary"
                onClick={() => {
                  setShown([]);
                  setRound(0);
                }}
              >
                Start over
              </Button>
            ) : null
          }
        />
      )}
    </PageContainer>
  );
}

function BackToMoods() {
  return (
    <Link
      href="/moods"
      className="inline-flex w-fit items-center gap-1.5 text-support font-semibold text-fg-secondary hover:text-fg"
    >
      <ArrowLeft className="size-4" /> All moods
    </Link>
  );
}
