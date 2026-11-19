import type { Metadata } from "next";

import { CreatePage } from "@/features/discovery/create-page";

export const metadata: Metadata = { title: "Create with words" };

export default function Page() {
  return <CreatePage />;
}
