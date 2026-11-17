import type { Metadata } from "next";

import { ArtistPage } from "@/features/discovery/detail-pages";

export const metadata: Metadata = { title: "Artist" };

export default async function Page({ params }: PageProps<"/artists/[id]">) {
  const { id } = await params;
  return <ArtistPage key={id} id={id} />;
}
