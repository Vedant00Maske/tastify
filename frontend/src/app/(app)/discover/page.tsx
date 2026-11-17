import type { Metadata } from "next";

import { DiscoverPage } from "@/features/discovery/discover-page";

export const metadata: Metadata = { title: "Discover" };

export default function Page() {
  return <DiscoverPage />;
}
