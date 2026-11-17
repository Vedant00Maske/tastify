import type { Metadata } from "next";

import { MoodDetailPage } from "@/features/discovery/mood-pages";

export const metadata: Metadata = { title: "Mood Mix" };

export default async function Page({ params }: PageProps<"/moods/[mood]">) {
  const { mood } = await params;
  return <MoodDetailPage key={mood} moodKey={mood} />;
}
