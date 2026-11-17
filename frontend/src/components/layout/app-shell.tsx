"use client";

import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { MusicPlayer } from "@/components/player/music-player";
import { Spinner } from "@/components/ui/states";
import { useMe } from "@/features/auth/queries";
import { usePlayer } from "@/stores/player";

import { AppHeader, AppSidebar, MobileNavigation } from "./navigation";

/** Sidebar, header, page content, player and mobile navigation for signed-in pages. */
export function AppShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();
  const hasPlayer = usePlayer((s) => s.queue.length > 0);

  useEffect(() => {
    if (me.data && !me.data.onboarding_completed) router.replace("/onboarding");
  }, [me.data, router]);

  return (
    <div className="flex h-dvh overflow-hidden">
      <a
        href="#main"
        className="sr-only z-50 rounded-button bg-accent px-4 py-2 font-semibold text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to content
      </a>
      <AppSidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <AppHeader />
        <main
          id="main"
          className={
            hasPlayer
              ? "flex-1 overflow-y-auto pb-36 lg:pb-24"
              : "flex-1 overflow-y-auto pb-20 lg:pb-6"
          }
        >
          {me.isPending ? (
            <div className="grid h-64 place-items-center text-fg-secondary">
              <Spinner className="size-6" />
            </div>
          ) : (
            children
          )}
        </main>
      </div>
      <MusicPlayer />
      <MobileNavigation />
    </div>
  );
}
