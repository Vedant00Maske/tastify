"use client";

import { Disc3, Heart, Play, Radio, UserRound } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { PageContainer, Section } from "@/components/layout/page";
import {
  AddToPlaylist,
  FeedbackButtons,
} from "@/components/feedback/feedback-buttons";
import { GeneratedCover, TrackArtwork } from "@/components/music/artwork";
import { fromRecommendation, toQueue } from "@/components/music/display";
import {
  CardsSkeleton,
  RowsSkeleton,
  TrackCards,
  TrackRows,
} from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import {
  EmptyState,
  ErrorState,
  Pill,
  Skeleton,
  Spinner,
} from "@/components/ui/states";
import { useFeedbackStates } from "@/features/feedback/queries";
import {
  useArtist,
  useArtistRadio,
  useSimilarArtists,
  useSimilarTracks,
  useTrack,
} from "@/features/recommendations/queries";
import {
  toUpdate,
  usePreferences,
  useUpdatePreferences,
} from "@/features/taste-profile/queries";
import { formatDuration, pluralize } from "@/lib/utils";
import { ApiError } from "@/services/api-client";
import { usePlayer } from "@/stores/player";

function NotFound({ what }: { what: string }) {
  return (
    <EmptyState
      title={`${what} not found`}
      description="It may not be in the TASTIFY catalogue."
      action={
        <Button asChild variant="secondary">
          <Link href="/search">Search instead</Link>
        </Button>
      }
    />
  );
}

function HeaderSkeleton() {
  return (
    <div className="flex flex-col gap-6 sm:flex-row sm:items-end">
      <Skeleton className="size-40 shrink-0 sm:size-52" />
      <div className="flex flex-1 flex-col gap-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-12 w-2/3" />
        <Skeleton className="h-4 w-1/3" />
      </div>
    </div>
  );
}

// --- artist ----------------------------------------------------------------------------------

function FollowButton({ artistId, name }: { artistId: string; name: string }) {
  const preferences = usePreferences();
  const save = useUpdatePreferences();
  if (!preferences.data) return null;
  const current = toUpdate(preferences.data);
  const favourite = current.preferred_artists.includes(artistId);
  return (
    <Button
      size="lg"
      variant={favourite ? "outline" : "secondary"}
      aria-pressed={favourite}
      disabled={save.isPending}
      onClick={() =>
        save.mutate(
          {
            ...current,
            preferred_artists: favourite
              ? current.preferred_artists.filter((a) => a !== artistId)
              : [...current.preferred_artists, artistId],
            excluded_artists: current.excluded_artists.filter(
              (a) => a !== artistId,
            ),
          },
          {
            onSuccess: () =>
              toast.success(
                favourite
                  ? `${name} removed from favourites`
                  : `${name} added to favourites`,
              ),
            onError: (error) => toast.error(error.message),
          },
        )
      }
    >
      {save.isPending ? (
        <Spinner />
      ) : (
        <Heart className={favourite ? "fill-current text-accent" : undefined} />
      )}
      {favourite ? "Favourite" : "Add to favourites"}
    </Button>
  );
}

function ArtistRadioSection({
  artistId,
  name,
}: {
  artistId: string;
  name: string;
}) {
  const radio = useArtistRadio(artistId);
  const play = usePlayer((s) => s.play);
  const tracks =
    radio.data?.recommendations.map((item) => fromRecommendation(item)) ?? [];
  return (
    <Section
      title={`${name} radio`}
      description="Starts with this artist and drifts to their neighbours."
      action={
        tracks.length ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => play(tracks.map(toQueue), 0)}
          >
            <Radio /> Play radio
          </Button>
        ) : undefined
      }
    >
      {radio.isPending ? (
        <RowsSkeleton count={6} />
      ) : radio.isError ? (
        <ErrorState onRetry={() => void radio.refetch()} />
      ) : tracks.length ? (
        <TrackRows
          label={`${name} radio`}
          tracks={tracks.slice(0, 15)}
          showReason
        />
      ) : (
        <p className="text-support text-fg-muted">
          No radio for this artist yet.
        </p>
      )}
    </Section>
  );
}

function SimilarArtistsSection({
  artistId,
  name,
}: {
  artistId: string;
  name: string;
}) {
  const similar = useSimilarArtists(artistId);
  const tracks =
    similar.data?.recommendations.map((item) => fromRecommendation(item)) ?? [];
  if (similar.isPending) return <CardsSkeleton layout="carousel" />;
  if (!tracks.length) return null;
  return (
    <Section
      title={`Fans of ${name} also like`}
      description="Tracks by related artists."
    >
      <TrackCards
        layout="carousel"
        label={`Similar to ${name}`}
        tracks={tracks}
      />
    </Section>
  );
}

export function ArtistPage({ id }: { id: string }) {
  const artist = useArtist(id);
  if (artist.isPending) {
    return (
      <PageContainer>
        <HeaderSkeleton />
        <RowsSkeleton />
      </PageContainer>
    );
  }
  if (artist.isError) {
    return (
      <PageContainer>
        {artist.error instanceof ApiError && artist.error.status === 404 ? (
          <NotFound what="Artist" />
        ) : (
          <ErrorState onRetry={() => void artist.refetch()} />
        )}
      </PageContainer>
    );
  }
  const data = artist.data;
  const facts = [
    data.artist_type,
    data.area,
    data.begin_year ? `since ${data.begin_year}` : null,
    pluralize(data.track_count, "track"),
  ].filter(Boolean);
  return (
    <PageContainer>
      <section className="flex flex-col gap-6 sm:flex-row sm:items-end">
        <div className="size-40 shrink-0 overflow-hidden rounded-full shadow-elevated sm:size-52">
          <GeneratedCover seed={data.id} label={data.name} round />
        </div>
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 text-meta font-semibold tracking-wider text-accent uppercase">
            <UserRound className="size-3.5" /> Artist
          </p>
          <h1 className="mt-1 font-display text-hero leading-none font-bold break-words">
            {data.name}
          </h1>
          <p className="mt-3 text-fg-secondary">{facts.join(" · ")}</p>
          {data.genres.length ? (
            <div className="mt-3 flex flex-wrap gap-1">
              {data.genres.slice(0, 8).map((genre) => (
                <Link
                  key={genre.name}
                  href={`/discover?genre=${encodeURIComponent(genre.name)}`}
                >
                  <Pill className="capitalize hover:text-fg">{genre.name}</Pill>
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      </section>
      <div className="flex flex-wrap gap-2">
        <FollowButton artistId={data.id} name={data.name} />
      </div>
      <ArtistRadioSection artistId={data.id} name={data.name} />
      <SimilarArtistsSection artistId={data.id} name={data.name} />
    </PageContainer>
  );
}

// --- track -----------------------------------------------------------------------------------

function SimilarTracksSection({
  trackId,
  title,
}: {
  trackId: string;
  title: string;
}) {
  const similar = useSimilarTracks(trackId);
  const tracks =
    similar.data?.recommendations.map((item) => fromRecommendation(item)) ?? [];
  if (similar.isPending) {
    return (
      <Section title="Similar tracks">
        <CardsSkeleton />
      </Section>
    );
  }
  if (similar.isError)
    return <ErrorState onRetry={() => void similar.refetch()} />;
  if (!tracks.length) return null;
  return (
    <Section
      title="Similar tracks"
      description={`Close to ${title} in sound and listeners.`}
    >
      <TrackCards label={`Similar to ${title}`} tracks={tracks} />
    </Section>
  );
}

export function TrackPage({ id }: { id: string }) {
  const track = useTrack(id);
  const stateOf = useFeedbackStates([id]);
  const play = usePlayer((s) => s.play);
  if (track.isPending) {
    return (
      <PageContainer>
        <HeaderSkeleton />
        <CardsSkeleton />
      </PageContainer>
    );
  }
  if (track.isError) {
    return (
      <PageContainer>
        {track.error instanceof ApiError && track.error.status === 404 ? (
          <NotFound what="Track" />
        ) : (
          <ErrorState onRetry={() => void track.refetch()} />
        )}
      </PageContainer>
    );
  }
  const data = track.data;
  const year = data.release_year ?? data.album?.release_year;
  const duration = formatDuration(data.duration_ms);
  return (
    <PageContainer>
      <section className="flex flex-col gap-6 sm:flex-row sm:items-end">
        <div className="w-40 shrink-0 sm:w-52">
          <TrackArtwork
            src={data.artwork_url}
            seed={data.id}
            label={data.artist}
            alt={`${data.title} artwork`}
            sizes="208px"
            className="shadow-elevated"
          />
        </div>
        <div className="min-w-0">
          <p className="inline-flex items-center gap-1.5 text-meta font-semibold tracking-wider text-accent uppercase">
            <Disc3 className="size-3.5" /> Track
          </p>
          <h1 className="mt-1 font-display text-hero leading-none font-bold break-words">
            {data.title}
          </h1>
          <p className="mt-3 text-fg-secondary">
            {data.credits.length
              ? data.credits.map((credit) => (
                  <span key={credit.artist_id}>
                    <Link
                      href={`/artists/${credit.artist_id}`}
                      className="font-semibold text-fg hover:underline"
                    >
                      {credit.name}
                    </Link>
                    {credit.join_phrase}
                  </span>
                ))
              : data.artist}
            {data.album ? <span> · {data.album.title}</span> : null}
            {year ? <span> · {year}</span> : null}
            {duration ? <span> · {duration}</span> : null}
          </p>
          {data.genres.length ? (
            <div className="mt-3 flex flex-wrap gap-1">
              {data.genres.slice(0, 8).map((genre) => (
                <Link
                  key={genre.name}
                  href={`/discover?genre=${encodeURIComponent(genre.name)}`}
                >
                  <Pill className="capitalize hover:text-fg">{genre.name}</Pill>
                </Link>
              ))}
            </div>
          ) : null}
        </div>
      </section>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="lg"
          onClick={() =>
            play(
              [
                {
                  id: data.id,
                  title: data.title,
                  artist: data.artist,
                  artistId: data.artist_id,
                  artworkUrl: data.artwork_url,
                },
              ],
              0,
            )
          }
        >
          <Play className="fill-current" /> Play
        </Button>
        <div className="flex items-center rounded-button bg-surface px-1">
          <FeedbackButtons
            trackId={data.id}
            title={data.title}
            state={stateOf(data.id)}
          />
          <AddToPlaylist trackId={data.id} title={data.title} />
        </div>
      </div>
      <SimilarTracksSection trackId={data.id} title={data.title} />
    </PageContainer>
  );
}
