"use client";

import { Clock, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { PageContainer, Section } from "@/components/layout/page";
import { ArtistCard } from "@/components/music/cards";
import { fromSummary } from "@/components/music/display";
import { RowsSkeleton, TrackRows } from "@/components/music/track-collections";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/form";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/primitives";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import {
  useArtistSearch,
  useTrackSearch,
} from "@/features/recommendations/queries";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useRecentSearches } from "@/hooks/use-recent-searches";

const MIN_LENGTH = 2;

function ArtistResults({ query, limit }: { query: string; limit: number }) {
  const artists = useArtistSearch(query, limit);
  if (artists.isPending) {
    return (
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="aspect-square rounded-full" />
        ))}
      </div>
    );
  }
  if (artists.isError)
    return <ErrorState onRetry={() => void artists.refetch()} />;
  if (!artists.data.results.length)
    return <p className="text-support text-fg-muted">No artists found.</p>;
  return (
    <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      {artists.data.results.map((artist) => (
        <ArtistCard
          key={artist.id}
          id={artist.id}
          name={artist.name}
          detail={
            artist.genres.slice(0, 2).join(", ") || artist.area || undefined
          }
          artworkUrl={artist.artwork_url}
        />
      ))}
    </div>
  );
}

function TrackResults({ query, limit }: { query: string; limit?: number }) {
  const tracks = useTrackSearch(query);
  const results = useMemo(
    () => (tracks.data?.results ?? []).slice(0, limit).map(fromSummary),
    [tracks.data, limit],
  );
  if (tracks.isPending) return <RowsSkeleton count={5} />;
  if (tracks.isError)
    return <ErrorState onRetry={() => void tracks.refetch()} />;
  if (!results.length)
    return <p className="text-support text-fg-muted">No tracks found.</p>;
  return <TrackRows label={`Tracks matching ${query}`} tracks={results} />;
}

export function SearchPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const urlQuery = params.get("q") ?? "";
  const [input, setInput] = useState(urlQuery);
  const query = useDebouncedValue(input.trim(), 300);
  const recent = useRecentSearches();
  const { add } = recent;

  // The last query this page wrote to the URL: any other ?q= change came from outside (the
  // header search bar, back/forward), and only those overwrite what the user is typing.
  const written = useRef(urlQuery);
  useEffect(() => {
    if (urlQuery === written.current) return;
    written.current = urlQuery;
    setInput(urlQuery);
  }, [urlQuery]);

  // Keep the URL shareable and remember the term once the user stops typing.
  useEffect(() => {
    if (query === written.current) return;
    written.current = query;
    router.replace(
      query ? `${pathname}?q=${encodeURIComponent(query)}` : pathname,
      { scroll: false },
    );
  }, [query, pathname, router]);
  useEffect(() => {
    if (query.length >= MIN_LENGTH) add(query);
  }, [query, add]);

  const active = query.length >= MIN_LENGTH;
  return (
    <PageContainer>
      <div role="search" className="relative max-w-2xl">
        <Search className="pointer-events-none absolute top-1/2 left-4 size-5 -translate-y-1/2 text-fg-muted" />
        <Input
          type="search"
          autoFocus
          aria-label="Search tracks and artists"
          placeholder="What do you want to hear?"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          className="h-14 rounded-full pr-12 pl-12 text-lg"
        />
        {input ? (
          <button
            type="button"
            aria-label="Clear search"
            onClick={() => setInput("")}
            className="absolute top-1/2 right-4 -translate-y-1/2 rounded-full p-1 text-fg-muted hover:text-fg"
          >
            <X className="size-4" />
          </button>
        ) : null}
      </div>

      {!active ? (
        recent.terms.length ? (
          <Section
            title="Recent searches"
            action={
              <Button variant="ghost" size="sm" onClick={recent.clear}>
                Clear all
              </Button>
            }
          >
            <ul className="flex flex-col gap-1">
              {recent.terms.map((term) => (
                <li key={term} className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setInput(term)}
                    className="flex flex-1 items-center gap-3 rounded-button px-3 py-2 text-left transition-colors hover:bg-surface"
                  >
                    <Clock className="size-4 text-fg-muted" aria-hidden />
                    {term}
                  </button>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Remove ${term} from recent searches`}
                    onClick={() => recent.remove(term)}
                  >
                    <X />
                  </Button>
                </li>
              ))}
            </ul>
          </Section>
        ) : (
          <EmptyState
            icon={Search}
            title="Search the catalogue"
            description="Find tracks and artists by name. Type at least two characters."
          />
        )
      ) : (
        <Tabs defaultValue="all" className="flex flex-col gap-6">
          <TabsList aria-label="Result type">
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="tracks">Tracks</TabsTrigger>
            <TabsTrigger value="artists">Artists</TabsTrigger>
          </TabsList>
          <TabsContent value="all" className="flex flex-col gap-10">
            <Section title="Artists">
              <ArtistResults query={query} limit={6} />
            </Section>
            <Section title="Tracks">
              <TrackResults query={query} limit={10} />
            </Section>
          </TabsContent>
          <TabsContent value="tracks">
            <TrackResults query={query} />
          </TabsContent>
          <TabsContent value="artists">
            <ArtistResults query={query} limit={24} />
          </TabsContent>
        </Tabs>
      )}
    </PageContainer>
  );
}
