"use client";

import { Activity, ArrowDownRight, ArrowUpRight, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ColumnChart, ShareBars, StatTile } from "@/components/charts/charts";
import { PageContainer, PageHeading, Section } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { percent, pointsChange, weekLabel } from "@/features/discovery/format";
import type { TasteAnalytics } from "@/types/api";

import { useTaste } from "./queries";

function Trends({ trends }: { trends: TasteAnalytics["trends"] }) {
  const [asTable, setAsTable] = useState(false);
  const total = trends.reduce((sum, w) => sum + w.playbacks, 0);
  const busiest = trends.reduce(
    (best, w) => (w.playbacks > best.playbacks ? w : best),
    trends[0],
  );
  return (
    <Section
      title="Listening trends"
      description={`${total.toLocaleString()} plays in ${trends.length} weeks; busiest week: ${weekLabel(busiest.week_start)} (${busiest.playbacks.toLocaleString()}).`}
      action={
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setAsTable((v) => !v)}
          aria-pressed={asTable}
        >
          {asTable ? "Show chart" : "Show table"}
        </Button>
      }
    >
      <div className="rounded-card-lg bg-surface p-4 shadow-card">
        {asTable ? (
          <div className="overflow-x-auto">
            <table className="w-full text-support">
              <caption className="sr-only">Weekly listening</caption>
              <thead className="text-left text-fg-muted">
                <tr>
                  <th scope="col" className="py-2 font-medium">
                    Week of
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    Plays
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    Tracks
                  </th>
                  <th scope="col" className="py-2 text-right font-medium">
                    New artists
                  </th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {trends.map((w) => (
                  <tr key={w.week_start} className="border-t border-border">
                    <td className="py-2">{weekLabel(w.week_start)}</td>
                    <td className="py-2 text-right">{w.playbacks}</td>
                    <td className="py-2 text-right">{w.distinct_tracks}</td>
                    <td className="py-2 text-right">{w.new_artists}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <ColumnChart
            data={trends.map((w) => ({
              key: w.week_start,
              value: w.playbacks,
            }))}
            label={`Weekly plays over the last ${trends.length} weeks`}
            formatTick={weekLabel}
            formatTooltip={(d) => {
              const week = trends.find((w) => w.week_start === d.key);
              return `Week of ${weekLabel(d.key)}: ${d.value} plays, ${week?.distinct_tracks ?? 0} tracks, ${week?.new_artists ?? 0} new artists`;
            }}
            height={220}
          />
        )}
      </div>
    </Section>
  );
}

function Shift({
  items,
  direction,
}: {
  items: TasteAnalytics["emerging"];
  direction: "up" | "down";
}) {
  const Icon = direction === "up" ? ArrowUpRight : ArrowDownRight;
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li
          key={item.genre}
          className="flex items-center justify-between gap-3 rounded-button bg-background-secondary px-3 py-2"
        >
          <span className="flex min-w-0 items-center gap-2">
            <Icon
              className={
                direction === "up"
                  ? "size-4 shrink-0 text-success"
                  : "size-4 shrink-0 text-warning"
              }
              aria-hidden
            />
            <span className="truncate capitalize">{item.genre}</span>
          </span>
          <span className="text-right text-meta text-fg-secondary tabular-nums">
            {percent(item.earlier_share)} → {percent(item.recent_share)}{" "}
            <span className="text-fg">({pointsChange(item.change)})</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

export function TastePage() {
  const taste = useTaste();

  if (taste.isPending) {
    return (
      <PageContainer>
        <Skeleton className="h-24" />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-28" />
          ))}
        </div>
        <Skeleton className="h-64" />
      </PageContainer>
    );
  }
  if (taste.isError) {
    return (
      <PageContainer>
        <ErrorState onRetry={() => void taste.refetch()} />
      </PageContainer>
    );
  }

  const data = taste.data;
  const hasListening = data.events > 0;
  const discovery = data.discovery;
  return (
    <PageContainer>
      <PageHeading
        title="Your taste"
        description={
          data.overview ??
          "What SONIQUEO has learned about your listening, from your own activity only."
        }
      />

      {!hasListening && !data.genres.length ? (
        <EmptyState
          icon={Activity}
          title="Nothing to show yet"
          description="Play, like and save some tracks. Your taste profile appears here as soon as there is enough to say something reliable."
          action={
            <Button asChild variant="secondary">
              <Link href="/discover">Start discovering</Link>
            </Button>
          }
        />
      ) : null}

      {discovery ? (
        <Section title="Discovery" description="The last 30 days.">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile
              value={discovery.new_artists_30d.toLocaleString()}
              label="New artists"
              hint="First played in 30 days"
            />
            <StatTile
              value={discovery.new_genres_30d.toLocaleString()}
              label="New genres"
              hint="First heard in 30 days"
            />
            <StatTile
              value={discovery.liked_tracks.toLocaleString()}
              label="Liked tracks"
            />
            <StatTile
              value={discovery.saved_tracks.toLocaleString()}
              label="Saved tracks"
            />
          </div>
          <p className="mt-3 text-support text-fg-secondary">
            <Sparkles className="mr-1 inline size-4 text-accent" aria-hidden />
            Your mixes aim for {percent(discovery.discovery_target)} new
            artists. Your measured appetite for new music is{" "}
            {percent(discovery.exploration_preference)} (0% sticks to
            favourites, 100% always explores).{" "}
            <Link
              href="/settings#preferences"
              className="font-semibold text-accent hover:underline"
            >
              Change
            </Link>
          </p>
        </Section>
      ) : null}

      <div className="grid gap-10 lg:grid-cols-2">
        {data.genres.length ? (
          <Section
            title="Genre affinity"
            description="Strength relative to your top genre (100)."
          >
            <div className="rounded-card-lg bg-surface p-4 shadow-card">
              <ShareBars
                label="Genre affinity"
                items={data.genres.map((g) => ({
                  key: g.genre,
                  label: g.genre,
                  value: g.score,
                }))}
                format={(v) => String(Math.round(v * 100))}
              />
            </div>
          </Section>
        ) : null}
        {data.artists.length ? (
          <Section
            title="Top artists"
            description="Your favourites and most-played artists."
          >
            <ol className="flex flex-col gap-1 rounded-card-lg bg-surface p-2 shadow-card">
              {data.artists.map((artist, i) => (
                <li key={artist.artist_id}>
                  <Link
                    href={`/artists/${artist.artist_id}`}
                    className="flex items-center gap-3 rounded-button px-2 py-2 transition-colors hover:bg-surface-hover"
                  >
                    <span className="w-5 text-right text-support text-fg-muted tabular-nums">
                      {i + 1}
                    </span>
                    <span className="min-w-0 flex-1 truncate font-medium">
                      {artist.name}
                    </span>
                    <span className="text-meta text-fg-secondary tabular-nums">
                      {artist.playbacks === 0
                        ? "Your pick"
                        : `${artist.playbacks.toLocaleString()} ${artist.playbacks === 1 ? "play" : "plays"}`}
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </Section>
        ) : null}
      </div>

      {data.trends.some((w) => w.playbacks > 0) ? (
        <Trends trends={data.trends} />
      ) : null}

      {data.emerging.length || data.fading.length ? (
        <Section
          title="How your taste is changing"
          description="Share of your plays in the last 14 days compared with before."
        >
          <div className="grid gap-6 md:grid-cols-2">
            {data.emerging.length ? (
              <div>
                <h3 className="mb-2 text-support font-semibold text-fg-secondary">
                  Growing
                </h3>
                <Shift items={data.emerging} direction="up" />
              </div>
            ) : null}
            {data.fading.length ? (
              <div>
                <h3 className="mb-2 text-support font-semibold text-fg-secondary">
                  Fading
                </h3>
                <Shift items={data.fading} direction="down" />
              </div>
            ) : null}
          </div>
        </Section>
      ) : hasListening ? (
        <p className="text-support text-fg-muted">
          Taste evolution appears once you have at least 10 plays both in the
          last 14 days and before.
        </p>
      ) : null}
    </PageContainer>
  );
}
