"use client";

import { Play, Shuffle, Sparkles } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { ColumnChart } from "@/components/charts/charts";
import { Carousel, PageContainer, Section } from "@/components/layout/page";
import { CollageArtwork } from "@/components/music/artwork";
import { MoodCard } from "@/components/music/cards";
import {
  fromRecommendation,
  fromSummary,
  toQueue,
  type DisplayTrack,
} from "@/components/music/display";
import {
  CardsSkeleton,
  TrackCards,
} from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { useMe } from "@/features/auth/queries";
import { useHistory } from "@/features/feedback/queries";
import {
  useBecauseYouListened,
  useForYou,
  useHiddenGems,
  useMoods,
  useSimilarArtists,
} from "@/features/recommendations/queries";
import {
  usePreferences,
  useTaste,
  useTasteProfile,
} from "@/features/taste-profile/queries";
import { greeting } from "@/lib/utils";
import { usePlayer } from "@/stores/player";

import { weekLabel } from "./format";

function Hero() {
  const forYou = useForYou(25);
  const play = usePlayer((s) => s.play);
  const playShuffled = usePlayer((s) => s.playShuffled);
  if (forYou.isPending) return <Skeleton className="h-64 rounded-card-lg" />;
  if (forYou.isError) {
    return (
      <ErrorState
        message="Your mix could not be loaded."
        onRetry={() => void forYou.refetch()}
      />
    );
  }
  const tracks = forYou.data.recommendations.map((item) =>
    fromRecommendation(item, forYou.data.request_id),
  );
  if (!tracks.length) {
    return (
      <EmptyState
        icon={Sparkles}
        title="Your mix is warming up"
        description="Like, save or play a few tracks and TASTIFY will build a mix around them."
        action={
          <Button asChild variant="secondary">
            <Link href="/discover">Start discovering</Link>
          </Button>
        }
      />
    );
  }
  const { familiar, discovery } = forYou.data.composition;
  const queue = tracks.map(toQueue);
  return (
    <div className="flex flex-col gap-6">
      <section
        aria-labelledby="hero-title"
        className="relative overflow-hidden rounded-card-lg bg-gradient-to-br from-accent-muted via-surface to-background-secondary p-5 shadow-card sm:p-8"
      >
        <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
          <div className="w-40 shrink-0 sm:w-48">
            <CollageArtwork
              urls={tracks
                .flatMap((t) => (t.artworkUrl ? [t.artworkUrl] : []))
                .slice(0, 4)}
              seed="for-you"
              label="For you"
            />
          </div>
          <div className="min-w-0">
            <p className="text-meta font-semibold tracking-wider text-accent uppercase">
              Made for you
            </p>
            <h2
              id="hero-title"
              className="mt-1 font-display text-hero leading-none font-bold"
            >
              Your mix
            </h2>
            <p className="mt-3 max-w-xl text-fg-secondary">
              {tracks.length} tracks: {familiar} from artists you know,{" "}
              {discovery} new to you. Starts with {tracks[0].title} by{" "}
              {tracks[0].artist}.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button size="lg" onClick={() => play(queue, 0)}>
                <Play className="fill-current" /> Play mix
              </Button>
              <Button
                size="lg"
                variant="secondary"
                onClick={() => playShuffled(queue)}
              >
                <Shuffle /> Shuffle
              </Button>
            </div>
          </div>
        </div>
      </section>
      <Section
        title="Recommended for you"
        description="Each pick says why it is here."
      >
        <TrackCards label="Recommended for you" tracks={tracks.slice(0, 10)} />
      </Section>
    </div>
  );
}

function Moods() {
  const moods = useMoods();
  const preferences = usePreferences();
  const ordered = useMemo(() => {
    const list = moods.data?.moods ?? [];
    const favourite = preferences.data?.preferred_moods ?? [];
    return [...list].sort(
      (a, b) =>
        (favourite.includes(a.key) ? 0 : 1) -
          (favourite.includes(b.key) ? 0 : 1) ||
        favourite.indexOf(a.key) - favourite.indexOf(b.key),
    );
  }, [moods.data, preferences.data]);
  if (!ordered.length) return null;
  return (
    <Section
      title="Made for your mood"
      action={
        <Link
          href="/moods"
          className="text-support font-semibold text-fg-secondary hover:text-fg"
        >
          All moods
        </Link>
      }
    >
      <Carousel label="Moods">
        {ordered.map((mood) => (
          <MoodCard
            key={mood.key}
            moodKey={mood.key}
            title={mood.title}
            description={mood.description}
          />
        ))}
      </Carousel>
    </Section>
  );
}

function BecauseYouListened() {
  const because = useBecauseYouListened();
  const sections =
    because.data?.sections.filter((s) => s.recommendations.length) ?? [];
  return sections.map((section) => (
    <Section
      key={section.seed.id}
      title={`Because you listened to ${section.seed.title}`}
      description={`${section.seed.artist} · ${section.source === "collaborative_item" ? "listeners who play it also play these" : "similar in sound"}`}
    >
      <TrackCards
        layout="carousel"
        label={`Because you listened to ${section.seed.title}`}
        tracks={section.recommendations.map((item) => fromRecommendation(item))}
      />
    </Section>
  ));
}

function HiddenGems() {
  const gems = useHiddenGems(15);
  if (gems.isPending) {
    return (
      <Section title="Hidden gems">
        <CardsSkeleton layout="carousel" />
      </Section>
    );
  }
  const tracks =
    gems.data?.recommendations.map((item) =>
      fromRecommendation(item, gems.data.request_id),
    ) ?? [];
  if (!tracks.length) return null;
  return (
    <Section
      title="Hidden gems"
      description="Lesser-known tracks that fit your taste."
    >
      <TrackCards layout="carousel" label="Hidden gems" tracks={tracks} />
    </Section>
  );
}

function SimilarToFavourites() {
  const profile = useTasteProfile();
  const top = profile.data?.artist_affinity[0];
  return top ? (
    <SimilarToArtist artistId={top.artist_id} name={top.name} />
  ) : null;
}

function SimilarToArtist({
  artistId,
  name,
}: {
  artistId: string;
  name: string;
}) {
  const similar = useSimilarArtists(artistId);
  const tracks =
    similar.data?.recommendations.map((item) => fromRecommendation(item)) ?? [];
  if (!tracks.length) return null;
  return (
    <Section
      title="Similar to your favourites"
      description={`Artists close to ${name}, your most-played artist.`}
      action={
        <Link
          href={`/artists/${artistId}`}
          className="text-support font-semibold text-fg-secondary hover:text-fg"
        >
          {name}
        </Link>
      }
    >
      <TrackCards
        layout="carousel"
        label={`Similar to ${name}`}
        tracks={tracks}
      />
    </Section>
  );
}

function RecentlyDiscovered() {
  const history = useHistory(["like", "save"], 30);
  const tracks = useMemo(() => {
    const seen = new Set<string>();
    const out: DisplayTrack[] = [];
    for (const item of history.data?.items ?? []) {
      if (!item.track || seen.has(item.track_id)) continue;
      seen.add(item.track_id);
      out.push(fromSummary(item.track));
    }
    return out.slice(0, 12);
  }, [history.data]);
  if (!tracks.length) return null;
  return (
    <Section
      title="Recently discovered"
      description="Tracks you liked or saved lately."
    >
      <TrackCards
        layout="carousel"
        label="Recently discovered"
        tracks={tracks}
        showReason={false}
      />
    </Section>
  );
}

function ListeningActivity() {
  const taste = useTaste();
  const data = taste.data;
  if (!data || data.events === 0 || !data.trends.some((w) => w.playbacks > 0))
    return null;
  const total = data.trends.reduce((sum, w) => sum + w.playbacks, 0);
  return (
    <Section
      title="Listening activity"
      description={`${total.toLocaleString()} plays over the last ${data.trends.length} weeks.`}
      action={
        <Link
          href="/taste"
          className="text-support font-semibold text-fg-secondary hover:text-fg"
        >
          Your taste
        </Link>
      }
    >
      <div className="rounded-card-lg bg-surface p-4 shadow-card">
        {data.overview ? (
          <p className="mb-4 text-fg-secondary">{data.overview}</p>
        ) : null}
        <ColumnChart
          data={data.trends.map((w) => ({
            key: w.week_start,
            value: w.playbacks,
          }))}
          label={`Weekly plays over the last ${data.trends.length} weeks`}
          formatTick={weekLabel}
          formatTooltip={(d) =>
            `Week of ${weekLabel(d.key)}: ${d.value.toLocaleString()} plays`
          }
          height={180}
        />
      </div>
    </Section>
  );
}

export function HomeDashboard() {
  const me = useMe();
  const name = me.data?.display_name?.trim();
  return (
    <PageContainer>
      <header>
        <h1 className="text-page font-bold">
          {greeting()}
          {name ? `, ${name}` : ""}
        </h1>
        <p className="mt-1 text-fg-secondary">
          Here is what TASTIFY found for you today.
        </p>
      </header>
      <Hero />
      <Moods />
      <BecauseYouListened />
      <HiddenGems />
      <SimilarToFavourites />
      <RecentlyDiscovered />
      <ListeningActivity />
    </PageContainer>
  );
}
