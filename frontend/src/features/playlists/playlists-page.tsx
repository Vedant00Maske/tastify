"use client";

import { ListMusic, Plus } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { PageContainer, PageHeading } from "@/components/layout/page";
import { PlaylistCard } from "@/components/music/cards";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { formatDuration, pluralize } from "@/lib/utils";
import type { PlaylistSummary } from "@/types/api";

import { CreatePlaylistDialog } from "./playlist-dialogs";
import { usePlaylists } from "./queries";

export function playlistDetail(playlist: PlaylistSummary): string {
  const parts = [pluralize(playlist.track_count, "track")];
  const duration = formatDuration(playlist.duration_ms);
  if (duration) parts.push(duration);
  if (playlist.kind === "generated") parts.push("Generated");
  return parts.join(" · ");
}

export function PlaylistsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const creating = params.get("new") === "1";
  const playlists = usePlaylists();
  const setCreating = (open: boolean) =>
    router.replace(open ? `${pathname}?new=1` : pathname, { scroll: false });

  return (
    <PageContainer>
      <PageHeading
        title="Playlists"
        description="Your collections. Generated playlists can be refreshed with new picks at any time."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus /> New playlist
          </Button>
        }
      />
      {playlists.isPending ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="aspect-[4/5]" />
          ))}
        </div>
      ) : playlists.isError ? (
        <ErrorState onRetry={() => void playlists.refetch()} />
      ) : playlists.data.playlists.length ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {playlists.data.playlists.map((playlist) => (
            <PlaylistCard
              key={playlist.id}
              id={playlist.id}
              name={playlist.name}
              detail={playlistDetail(playlist)}
              artworkUrls={playlist.artwork_urls}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={ListMusic}
          title="No playlists yet"
          description="Create one from scratch, or start from your mix, hidden gems or a mood."
          action={
            <Button onClick={() => setCreating(true)}>
              <Plus /> New playlist
            </Button>
          }
        />
      )}
      <CreatePlaylistDialog open={creating} onOpenChange={setCreating} />
    </PageContainer>
  );
}
