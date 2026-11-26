"use client";

import {
  ArrowRight,
  Dices,
  History,
  ListPlus,
  Play,
  Shuffle,
} from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useId, useMemo, useState } from "react";
import { toast } from "sonner";

import { ColumnChart } from "@/components/charts/charts";
import {
  HideOnDislikeProvider,
  useHideOnDislike,
} from "@/components/feedback/hide-on-dislike";
import { Carousel, PageContainer, Section } from "@/components/layout/page";
import { CollageArtwork } from "@/components/music/artwork";
import { MoodCard, TrackRow } from "@/components/music/cards";
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
import { Input, Label } from "@/components/ui/form";
import { ErrorState, Skeleton, Spinner } from "@/components/ui/states";
import { useFeedbackStates, useHistory } from "@/features/feedback/queries";
import { useCreatePlaylist } from "@/features/playlists/queries";
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
import { easeOutSoft } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { usePlayer } from "@/stores/player";
import type { PersonalizedResponse } from "@/types/api";

import { ExplorationControl } from "./exploration-control";
import { weekLabel } from "./format";

const MIX_SIZE = 25;
/** Tracklist rows shown before "Show all": below 1280 px, and from 1280 px up. */
const ROWS_SMALL = 5;
const ROWS_LARGE = 8;
/** The session nudge needs this many recent events (backend: recommendations/context.py). */
const MIN_SESSION_EVENTS = 2;

const panel =
  "rounded-card-lg bg-linear-to-br from-accent-muted via-surface to-background-secondary p-5 shadow-card sm:p-8";
/** Two columns from 1280 px (the sidebar leaves too little room below that): the mix's notes on the left, its tracklist on the right. */
const heroGrid =
  "grid gap-8 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] xl:grid-rows-[auto_1fr] xl:gap-x-12";

function count(n: number, some: string, none: string) {
  return n > 0 ? (
    <>
      <span className="text-fg tabular-nums">{n}</span> {some}
    </>
  ) : (
    none
  );
}

/** What the mix is made of, in one sentence, from the response's composition. */
function Composition({
  data,
  tracks,
  refreshing,
}: {
  data: PersonalizedResponse;
  tracks: DisplayTrack[];
  refreshing: boolean;
}) {
  // Describe the mix as it stands now: tracks the listener hid are no longer part of it.
  const hider = useHideOnDislike();
  const playable = tracks.filter((t) => !hider?.isHidden(t.id));
  const discovery = playable.filter((t) => t.discovery).length;
  const familiar = playable.length - discovery;
  const first = playable[0];
  const context = data.context ?? {};
  const sessionApplied =
    Number(context.session_weight ?? 0) > 0 &&
    Number(context.session_events ?? 0) >= MIN_SESSION_EVENTS;
  return (
    <div className="flex flex-col gap-2">
      <p
        aria-live="polite"
        className={cn(
          "max-w-xl text-fg-secondary transition-opacity duration-200",
          refreshing && "opacity-60",
        )}
      >
        {first ? (
          <>
            <span className="text-fg tabular-nums">{playable.length}</span>{" "}
            {playable.length === 1 ? "track" : "tracks"}:{" "}
            {count(
              familiar,
              "from artists you know",
              "none from artists you know",
            )}
            , {count(discovery, "new to you", "none new to you")}. Starts with{" "}
            {first.title} by {first.artist}.
          </>
        ) : (
          "You have hidden every track in this mix. Change the balance below, or describe what you want to hear."
        )}
        {refreshing ? (
          <Spinner className="ml-2 size-3.5 align-[-2px] text-fg-muted" />
        ) : null}
      </p>
      {sessionApplied ? (
        <p className="flex items-center gap-2 text-support text-fg-secondary">
          <History className="size-4 shrink-0 text-fg-muted" aria-hidden />
          Leaning toward what you played in the last hour.
        </p>
      ) : null}
    </div>
  );
}

/** "Describe what you want to hear": hands the words to the Create page, which runs them. */
function PromptField({ className }: { className?: string }) {
  const router = useRouter();
  const id = useId();
  const [text, setText] = useState("");
  return (
    <form
      className={cn("flex flex-col gap-1.5", className)}
      onSubmit={(event) => {
        event.preventDefault();
        const clean = text.trim();
        if (clean.length < 2) return;
        router.push(`/create?prompt=${encodeURIComponent(clean)}`);
      }}
    >
      <Label htmlFor={id}>Describe what you want to hear</Label>
      <div className="relative">
        <Input
          id={id}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Dream pop for a rainy afternoon, new artists"
          autoComplete="off"
          className="pr-12"
        />
        <Button
          type="submit"
          variant="ghost"
          size="icon"
          aria-label="Create a playlist from this description"
          className="absolute top-0.5 right-0.5"
        >
          <ArrowRight />
        </Button>
      </div>
    </form>
  );
}

/** The mix as liner notes: a numbered tracklist with a reason on every line. */
function Tracklist({
  tracks,
  refreshing,
}: {
  tracks: DisplayTrack[];
  refreshing: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const stateOf = useFeedbackStates(tracks.map((t) => t.id));
  const play = usePlayer((s) => s.play);
  const hider = useHideOnDislike();
  const playFrom = (track: DisplayTrack) => {
    const playable = tracks.filter((t) => !hider?.isHidden(t.id));
    const at = playable.findIndex((t) => t.id === track.id);
    play(playable.map(toQueue), Math.max(at, 0));
  };
  return (
    <div className="flex min-w-0 flex-col gap-2 xl:col-start-2 xl:row-span-2 xl:row-start-1">
      <h2 className="sr-only">Tracklist</h2>
      <ol
        aria-label="Your mix tracklist"
        className={cn(
          // Rounded so the focus ring it takes after "Exclude <artist>" matches the card shapes.
          "flex flex-col rounded-card transition-opacity duration-200",
          refreshing && "opacity-60",
        )}
      >
        <AnimatePresence initial={false} mode="popLayout">
          {tracks.map((track, i) => (
            <motion.li
              key={track.id}
              layout="position"
              initial={{ opacity: 0, y: 6 }}
              animate={{
                opacity: 1,
                y: 0,
                transition: {
                  duration: 0.22,
                  ease: easeOutSoft,
                  delay: Math.min(i, ROWS_LARGE) * 0.03,
                },
              }}
              exit={{ opacity: 0, transition: { duration: 0.12 } }}
              className={cn(
                !expanded && i >= ROWS_SMALL && "max-xl:hidden",
                !expanded && i >= ROWS_LARGE && "hidden",
              )}
            >
              <TrackRow
                track={track}
                index={i}
                state={stateOf(track.id)}
                onPlay={() => playFrom(track)}
                showReason
              />
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        {tracks.length > ROWS_SMALL ? (
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
            className={cn(
              tracks.length <= ROWS_LARGE && !expanded && "xl:invisible",
            )}
          >
            {expanded ? "Show fewer" : `Show all ${tracks.length} tracks`}
          </Button>
        ) : (
          <span />
        )}
        <SaveMix tracks={tracks} />
      </div>
    </div>
  );
}

/** Keep this mix: a generated playlist that can be exported to a connected service. */
function SaveMix({ tracks }: { tracks: DisplayTrack[] }) {
  const router = useRouter();
  const hider = useHideOnDislike();
  const create = useCreatePlaylist();
  const playable = tracks.filter((t) => !hider?.isHidden(t.id));
  const save = () => {
    const name = `Your mix · ${new Intl.DateTimeFormat("en-GB", {
      day: "numeric",
      month: "short",
    }).format(new Date())}`;
    create.mutate(
      {
        name,
        track_ids: playable.map((t) => t.id),
        generator: { collection: "for_you", size: MIX_SIZE },
      },
      {
        onSuccess: (playlist) =>
          toast.success(`Saved "${playlist.name}"`, {
            action: {
              label: "Open",
              onClick: () => router.push(`/playlists/${playlist.id}`),
            },
          }),
        onError: () => toast.error("Could not save the mix. Try again."),
      },
    );
  };
  return (
    <Button
      variant="outline"
      disabled={!playable.length || create.isPending}
      onClick={save}
    >
      {create.isPending ? <Spinner /> : <ListPlus />} Save as playlist
    </Button>
  );
}

function MixActions({ tracks }: { tracks: DisplayTrack[] }) {
  const play = usePlayer((s) => s.play);
  const playShuffled = usePlayer((s) => s.playShuffled);
  const hider = useHideOnDislike();
  const queue = tracks.filter((t) => !hider?.isHidden(t.id)).map(toQueue);
  return (
    <div className="flex flex-wrap gap-2">
      <Button size="lg" disabled={!queue.length} onClick={() => play(queue, 0)}>
        <Play className="fill-current" /> Play mix
      </Button>
      <Button
        size="lg"
        variant="secondary"
        disabled={!queue.length}
        onClick={() => playShuffled(queue)}
      >
        <Shuffle /> Shuffle
      </Button>
    </div>
  );
}

function MixHeroSkeleton() {
  return (
    <section aria-busy aria-labelledby="mix-title" className={panel}>
      <div className={heroGrid}>
        <div className="flex min-w-0 flex-col gap-6">
          <div className="flex items-end gap-5">
            <Skeleton className="size-24 shrink-0 rounded-button sm:size-32" />
            <h1
              id="mix-title"
              className="font-display text-hero leading-none font-bold"
            >
              Your mix
            </h1>
          </div>
          <div className="flex flex-col gap-2">
            <Skeleton className="h-4 w-full max-w-md" />
            <Skeleton className="h-4 w-2/3 max-w-sm" />
          </div>
          <Skeleton className="h-12 w-full max-w-sm rounded-full" />
          <div className="flex flex-wrap gap-2">
            <Skeleton className="h-12 w-36 rounded-button" />
            <Skeleton className="h-12 w-28 rounded-button" />
          </div>
        </div>
        <div className="flex flex-col gap-1 xl:col-start-2 xl:row-span-2 xl:row-start-1">
          {Array.from({ length: ROWS_LARGE }, (_, i) => (
            <div
              key={i}
              className={cn(
                "flex items-center gap-3 px-2 py-2",
                i >= ROWS_SMALL && "max-xl:hidden",
              )}
            >
              <Skeleton className="size-12 rounded-button-sm" />
              <div className="flex flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-3 w-1/3" />
              </div>
            </div>
          ))}
        </div>
        <Skeleton className="h-11 w-full xl:col-start-1 xl:row-start-2" />
      </div>
    </section>
  );
}

/** No mix yet (a new listener): words and moods work without any history. */
function ColdStartHero() {
  return (
    <section aria-labelledby="mix-title" className={panel}>
      <div className="flex max-w-2xl flex-col gap-5">
        <h1
          id="mix-title"
          className="font-display text-hero leading-none font-bold"
        >
          Your mix starts here
        </h1>
        <p className="text-fg-secondary">
          SONIQUEO builds your mix from the tracks you like, save and dislike,
          and from listening history you import. Until then, describe what you
          want to hear, or start from a mood below.
        </p>
        <PromptField />
        <div>
          <Button asChild variant="secondary">
            <Link href="/discover#surprise-title">
              <Dices /> Surprise me
            </Link>
          </Button>
        </div>
      </div>
    </section>
  );
}

function MixHero() {
  const forYou = useForYou(MIX_SIZE);
  const data = forYou.data;
  const tracks = useMemo(
    () =>
      data?.recommendations.map((item) =>
        fromRecommendation(item, data.request_id),
      ) ?? [],
    [data],
  );
  if (forYou.isPending) return <MixHeroSkeleton />;
  if (!data) {
    return (
      <section aria-labelledby="mix-title" className="flex flex-col gap-4">
        <h1 id="mix-title" className="text-page font-bold">
          Your mix
        </h1>
        <ErrorState
          message="Your mix could not be loaded. Retry, or start from a mood below."
          onRetry={() => void forYou.refetch()}
        />
      </section>
    );
  }
  if (!tracks.length) return <ColdStartHero />;

  const refreshing = forYou.isFetching;
  return (
    <section aria-labelledby="mix-title" className={panel}>
      <div className={heroGrid}>
        <div className="flex min-w-0 flex-col gap-6 xl:col-start-1 xl:row-start-1">
          <div className="flex items-end gap-5">
            <div className="w-24 shrink-0 sm:w-32">
              <CollageArtwork
                urls={tracks
                  .flatMap((t) => (t.artworkUrl ? [t.artworkUrl] : []))
                  .slice(0, 4)}
                seed={`mix-${tracks[0].id}`}
                label=""
              />
            </div>
            <h1
              id="mix-title"
              className="font-display text-hero leading-none font-bold"
            >
              Your mix
            </h1>
          </div>
          <Composition data={data} tracks={tracks} refreshing={refreshing} />
          {forYou.isError ? (
            <p
              role="alert"
              className="flex flex-wrap items-center gap-2 text-support text-fg-secondary"
            >
              Your mix could not be refreshed, so this is the last one that
              loaded.
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void forYou.refetch()}
              >
                Retry
              </Button>
            </p>
          ) : null}
          <ExplorationControl
            effectiveMode={data.composition.exploration_mode}
          />
          <MixActions tracks={tracks} />
        </div>
        <Tracklist tracks={tracks} refreshing={refreshing} />
        <PromptField className="xl:col-start-1 xl:row-start-2 xl:self-start" />
      </div>
    </section>
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
  if (moods.isPending) {
    // Hold the row's place so the sections below do not jump when moods arrive.
    return (
      <Section title="Made for your mood">
        <div aria-busy className="flex gap-4 overflow-hidden">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton
              key={i}
              className="aspect-4/3 w-[44vw] max-w-55 shrink-0 rounded-card-lg sm:w-52.5"
            />
          ))}
        </div>
      </Section>
    );
  }
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
            compact
          />
        ))}
      </Carousel>
    </Section>
  );
}

/**
 * The tracks already in the mix, so the rows below never repeat them (the mix is shown once).
 * `null` while the mix loads: the rows wait rather than shuffle when it arrives.
 */
function useMixIds(): Set<string> | null {
  const forYou = useForYou(MIX_SIZE);
  return useMemo(() => {
    if (forYou.isPending) return null;
    return new Set(forYou.data?.recommendations.map((r) => r.track_id) ?? []);
  }, [forYou.isPending, forYou.data]);
}

function notInMix(tracks: DisplayTrack[], mix: Set<string>) {
  return tracks.filter((t) => !mix.has(t.id));
}

/** At most two seed tracks, so these rows never push the rest of the page out of reach. */
function BecauseYouListened() {
  const because = useBecauseYouListened();
  const mix = useMixIds();
  if (because.isPending || !mix) {
    return (
      <div aria-busy className="flex flex-col gap-4">
        <Skeleton className="h-6 w-72 max-w-full" />
        <CardsSkeleton layout="carousel" />
      </div>
    );
  }
  const sections =
    because.data?.sections
      .map((section) => ({
        ...section,
        tracks: notInMix(
          section.recommendations.map((item) => fromRecommendation(item)),
          mix,
        ),
      }))
      .filter((s) => s.tracks.length)
      .slice(0, 2) ?? [];
  return sections.map((section) => (
    <Section
      key={section.seed.id}
      title={`Because you listened to ${section.seed.title}`}
      description={`${section.seed.artist} · ${section.source === "collaborative_item" ? "listeners who play it also play these" : "similar in sound"}`}
    >
      <TrackCards
        layout="carousel"
        label={`Because you listened to ${section.seed.title}`}
        tracks={section.tracks}
      />
    </Section>
  ));
}

function HiddenGems() {
  const gems = useHiddenGems(15);
  const mix = useMixIds();
  if (gems.isPending || !mix) {
    return (
      <Section title="Hidden gems">
        <CardsSkeleton layout="carousel" />
      </Section>
    );
  }
  const tracks = notInMix(
    gems.data?.recommendations.map((item) =>
      fromRecommendation(item, gems.data.request_id),
    ) ?? [],
    mix,
  );
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
  const mix = useMixIds();
  const tracks = notInMix(
    similar.data?.recommendations.map((item) => fromRecommendation(item)) ?? [],
    mix ?? new Set(),
  );
  if (!mix || !tracks.length) return null;
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
  return (
    <HideOnDislikeProvider>
      <PageContainer>
        <MixHero />
        <Moods />
        <BecauseYouListened />
        <HiddenGems />
        <SimilarToFavourites />
        <RecentlyDiscovered />
        <ListeningActivity />
      </PageContainer>
    </HideOnDislikeProvider>
  );
}
