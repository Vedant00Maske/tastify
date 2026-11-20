"use client";

import { Dices, Radio, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";

import { GenreCard } from "@/components/music/cards";
import { fromRecommendation } from "@/components/music/display";
import { PageContainer, PageHeading, Section } from "@/components/layout/page";
import {
  CardsSkeleton,
  TrackCards,
  TrackRows,
} from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Pill } from "@/components/ui/states";
import { useHistory } from "@/features/feedback/queries";
import {
  useArtistRadio,
  useGenreRecommendations,
  useGenres,
  useHiddenGems,
  usePopular,
  useSimilarTracks,
  useSurprise,
} from "@/features/recommendations/queries";
import {
  usePreferences,
  useTasteProfile,
} from "@/features/taste-profile/queries";
import { cn, pluralize } from "@/lib/utils";
import type { RecommendationItem } from "@/types/api";

export const VIEWS = [
  { key: "all", label: "Everything" },
  { key: "trending", label: "Trending" },
  { key: "gems", label: "Hidden gems" },
  { key: "radio", label: "Artist radio" },
  { key: "similar", label: "Similar" },
] as const;
type View = (typeof VIEWS)[number]["key"];

function useDiscoveryOnly(
  items: RecommendationItem[] | undefined,
  discoveriesOnly: boolean,
) {
  return useMemo(
    () =>
      (items ?? [])
        .filter((item) => !discoveriesOnly || item.discovery)
        .map((item) => fromRecommendation(item)),
    [items, discoveriesOnly],
  );
}

/** One random pick from an artist the user has never played (a fresh draw on every click). */
function SurpriseResult() {
  const surprise = useSurprise();
  const pick = surprise.data?.recommendations[0];
  return (
    <section
      aria-labelledby="surprise-title"
      className="flex flex-col gap-4 rounded-card-lg bg-gradient-to-br from-accent-muted to-surface p-5 shadow-card"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 id="surprise-title" className="text-section font-bold">
            Surprise me
          </h2>
          <p className="mt-1 max-w-lg text-support text-fg-secondary">
            One track from an artist you have never played, drawn at random from
            the ones that fit your taste best.
          </p>
        </div>
        <Button
          size="lg"
          onClick={() => surprise.mutate()}
          disabled={surprise.isPending}
          className="shrink-0"
        >
          <Dices /> {pick ? "Another one" : "Surprise me"}
        </Button>
      </div>
      {surprise.isError ? (
        <p role="alert" className="text-support text-error">
          Could not find a surprise right now. Try again.
        </p>
      ) : null}
      {surprise.data && !pick ? (
        <p className="text-support text-fg-secondary">
          Nothing new to suggest yet. Like or play a few more tracks first.
        </p>
      ) : null}
      {pick ? (
        <div className="rounded-card bg-background/40 p-1">
          <TrackRows
            label="Your surprise"
            tracks={[fromRecommendation(pick, surprise.data?.request_id)]}
            showReason
          />
        </div>
      ) : null}
    </section>
  );
}

function GenreResults({
  genre,
  discoveriesOnly,
}: {
  genre: string;
  discoveriesOnly: boolean;
}) {
  const recs = useGenreRecommendations(genre);
  const tracks = useDiscoveryOnly(recs.data?.recommendations, discoveriesOnly);
  return (
    <Section
      title={`Top in ${genre}`}
      description="The strongest tracks tagged with this genre."
    >
      {recs.isPending ? (
        <CardsSkeleton />
      ) : recs.isError ? (
        <ErrorState onRetry={() => void recs.refetch()} />
      ) : tracks.length ? (
        <TrackCards label={`Top in ${genre}`} tracks={tracks} />
      ) : (
        <EmptyState
          title="Nothing here yet"
          description="No tracks match this genre and filter."
        />
      )}
    </Section>
  );
}

function Trending({ discoveriesOnly }: { discoveriesOnly: boolean }) {
  const trending = usePopular("trending");
  const tracks = useDiscoveryOnly(
    trending.data?.recommendations,
    discoveriesOnly,
  );
  if (trending.isPending) return <CardsSkeleton layout="carousel" />;
  if (!tracks.length) return null;
  return (
    <Section
      title="Trending"
      description="What listeners are playing most right now."
    >
      <TrackCards layout="carousel" label="Trending" tracks={tracks} />
    </Section>
  );
}

function Gems({ discoveriesOnly }: { discoveriesOnly: boolean }) {
  const gems = useHiddenGems(20);
  const tracks = useDiscoveryOnly(gems.data?.recommendations, discoveriesOnly);
  if (gems.isPending) return <CardsSkeleton layout="carousel" />;
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

function ArtistRadio({ discoveriesOnly }: { discoveriesOnly: boolean }) {
  const profile = useTasteProfile();
  const preferences = usePreferences();
  const artists = useMemo(() => {
    const seen = new Map<string, string>();
    for (const a of profile.data?.artist_affinity ?? [])
      seen.set(a.artist_id, a.name);
    for (const a of preferences.data?.preferred_artists ?? [])
      seen.set(a.artist_id, a.name);
    return [...seen.entries()].slice(0, 8).map(([id, name]) => ({ id, name }));
  }, [profile.data, preferences.data]);
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = artists.find((a) => a.id === chosen) ?? artists[0];
  if (!selected) return null;
  return (
    <Section
      title="Artist radio"
      description="A station that starts with one artist and drifts to their neighbours."
    >
      <div
        className="mb-4 flex flex-wrap gap-2"
        role="group"
        aria-label="Radio station"
      >
        {artists.map((artist) => (
          <button
            key={artist.id}
            type="button"
            aria-pressed={artist.id === selected.id}
            onClick={() => setChosen(artist.id)}
          >
            <Pill
              active={artist.id === selected.id}
              className="px-3 py-1 text-support"
            >
              <Radio className="size-3.5" /> {artist.name}
            </Pill>
          </button>
        ))}
      </div>
      <RadioStation
        artistId={selected.id}
        name={selected.name}
        discoveriesOnly={discoveriesOnly}
      />
    </Section>
  );
}

function RadioStation({
  artistId,
  name,
  discoveriesOnly,
}: {
  artistId: string;
  name: string;
  discoveriesOnly: boolean;
}) {
  const radio = useArtistRadio(artistId);
  const tracks = useDiscoveryOnly(radio.data?.recommendations, discoveriesOnly);
  if (radio.isPending) return <CardsSkeleton layout="carousel" />;
  if (radio.isError) return <ErrorState onRetry={() => void radio.refetch()} />;
  if (!tracks.length)
    return <EmptyState title={`No station for ${name} yet`} />;
  return (
    <TrackCards layout="carousel" label={`${name} radio`} tracks={tracks} />
  );
}

function SimilarToLiked({ discoveriesOnly }: { discoveriesOnly: boolean }) {
  const liked = useHistory(["like", "save"], 5);
  const seed = liked.data?.items.find((i) => i.track)?.track;
  return seed ? (
    <SimilarTo
      trackId={seed.id}
      title={seed.title}
      artist={seed.artist}
      discoveriesOnly={discoveriesOnly}
    />
  ) : null;
}

function SimilarTo({
  trackId,
  title,
  artist,
  discoveriesOnly,
}: {
  trackId: string;
  title: string;
  artist: string;
  discoveriesOnly: boolean;
}) {
  const similar = useSimilarTracks(trackId);
  const tracks = useDiscoveryOnly(
    similar.data?.recommendations,
    discoveriesOnly,
  );
  if (!tracks.length) return null;
  return (
    <Section
      title={`Similar to ${title}`}
      description={`Close in sound and listeners to ${artist}, a track you liked.`}
    >
      <TrackCards
        layout="carousel"
        label={`Similar to ${title}`}
        tracks={tracks}
      />
    </Section>
  );
}

export function DiscoverPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const genre = params.get("genre");
  const view = (VIEWS.find((v) => v.key === params.get("view"))?.key ??
    "all") as View;
  const discoveriesOnly = params.get("new") === "1";
  const genres = useGenres();

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, {
      scroll: false,
    });
  };
  const show = (key: View) => view === "all" || view === key;

  return (
    <PageContainer>
      <PageHeading
        title="Discover"
        description="Browse by genre, follow an artist's radio, or let SONIQUEO surprise you."
      />
      <SurpriseResult />

      <div className="sticky top-0 z-10 -mx-4 flex flex-col gap-3 bg-background/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 lg:-mx-10 lg:px-10">
        <div
          className="scrollbar-none flex items-center gap-2 overflow-x-auto"
          role="group"
          aria-label="Show"
        >
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              aria-pressed={view === v.key}
              onClick={() => setParam("view", v.key === "all" ? null : v.key)}
              className={cn(
                "shrink-0 rounded-full px-3.5 py-1.5 text-support font-semibold transition-colors",
                view === v.key
                  ? "bg-fg text-background"
                  : "bg-surface text-fg-secondary hover:bg-surface-hover hover:text-fg",
              )}
            >
              {v.label}
            </button>
          ))}
          <span className="mx-1 h-5 w-px shrink-0 bg-border" aria-hidden />
          <button
            type="button"
            aria-pressed={discoveriesOnly}
            onClick={() => setParam("new", discoveriesOnly ? null : "1")}
            className={cn(
              "shrink-0 rounded-full border px-3.5 py-1.5 text-support font-semibold transition-colors",
              discoveriesOnly
                ? "border-accent bg-accent-muted text-accent"
                : "border-border text-fg-secondary hover:text-fg",
            )}
          >
            New artists only
          </button>
          {genre ? (
            <button
              type="button"
              onClick={() => setParam("genre", null)}
              className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent px-3.5 py-1.5 text-support font-semibold text-on-accent capitalize"
            >
              {genre} <X className="size-3.5" aria-label="Clear genre" />
            </button>
          ) : null}
        </div>
      </div>

      {genre ? (
        <GenreResults genre={genre} discoveriesOnly={discoveriesOnly} />
      ) : null}

      {!genre && (genres.data?.genres.length ?? 0) > 0 ? (
        <Section
          title="Browse genres"
          description="The genres with the most tracks in the catalogue."
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {genres.data?.genres.slice(0, 18).map((g) => (
              <GenreCard
                key={g.name}
                name={g.name}
                detail={pluralize(g.tracks, "track")}
                href={`/discover?genre=${encodeURIComponent(g.name)}`}
              />
            ))}
          </div>
        </Section>
      ) : null}

      {show("trending") ? <Trending discoveriesOnly={discoveriesOnly} /> : null}
      {show("gems") ? <Gems discoveriesOnly={discoveriesOnly} /> : null}
      {show("radio") ? <ArtistRadio discoveriesOnly={discoveriesOnly} /> : null}
      {show("similar") ? (
        <SimilarToLiked discoveriesOnly={discoveriesOnly} />
      ) : null}

      <p className="text-meta text-fg-muted">
        Looking for something specific?{" "}
        <Link href="/search" className="underline hover:text-fg">
          Search the catalogue
        </Link>
        .
      </p>
    </PageContainer>
  );
}
