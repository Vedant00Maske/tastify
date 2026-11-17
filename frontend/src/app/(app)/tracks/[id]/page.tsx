import type { Metadata } from "next";

import { TrackPage } from "@/features/discovery/detail-pages";

export const metadata: Metadata = { title: "Track" };

export default async function Page({ params }: PageProps<"/tracks/[id]">) {
  const { id } = await params;
  return <TrackPage key={id} id={id} />;
}
