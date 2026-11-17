import type { Metadata } from "next";

import { PlaylistsPage } from "@/features/playlists/playlists-page";

export const metadata: Metadata = { title: "Playlists" };

export default function Page() {
  return <PlaylistsPage />;
}
