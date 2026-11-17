import type { Metadata } from "next";

import { PlaylistDetailPage } from "@/features/playlists/playlist-detail";

export const metadata: Metadata = { title: "Playlist" };

export default async function Page({ params }: PageProps<"/playlists/[id]">) {
  const { id } = await params;
  return <PlaylistDetailPage key={id} id={id} />;
}
