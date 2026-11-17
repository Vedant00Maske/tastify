import type { Metadata } from "next";

import { MoodsPage } from "@/features/discovery/mood-pages";

export const metadata: Metadata = { title: "Mood Mix" };

export default function Page() {
  return <MoodsPage />;
}
