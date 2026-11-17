import type { Metadata } from "next";

import { TastePage } from "@/features/taste-profile/taste-page";

export const metadata: Metadata = { title: "Your taste" };

export default function Page() {
  return <TastePage />;
}
