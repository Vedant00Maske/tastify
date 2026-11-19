"use client";

import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import { MotionConfig } from "motion/react";
import { useState, type ReactNode } from "react";
import { Toaster } from "sonner";

import { OfflineBanner } from "@/components/feedback/offline-banner";
import { hardNavigate, isLeaving } from "@/lib/navigation";
import { ApiError } from "@/services/api-client";

const AUTH_PAGES = ["/login", "/register"];

function onUnauthorized(error: unknown) {
  if (!(error instanceof ApiError) || !error.isUnauthorized) return;
  if (typeof window === "undefined" || isLeaving()) return;
  const { pathname, search } = window.location;
  if (AUTH_PAGES.includes(pathname)) return;
  hardNavigate(`/login?next=${encodeURIComponent(pathname + search)}`);
}

function makeClient() {
  return new QueryClient({
    queryCache: new QueryCache({ onError: onUnauthorized }),
    mutationCache: new MutationCache({ onError: onUnauthorized }),
    defaultOptions: {
      queries: {
        staleTime: 60_000,
        refetchOnWindowFocus: false,
        // Client errors (4xx) will not fix themselves; retry only network and server errors.
        retry: (failures, error) =>
          !(error instanceof ApiError && error.status < 500) && failures < 2,
      },
    },
  });
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <QueryClientProvider client={client}>
      <MotionConfig reducedMotion="user">
        {children}
        <OfflineBanner />
      </MotionConfig>
      <Toaster
        theme="dark"
        position="bottom-center"
        offset={96}
        toastOptions={{
          classNames: {
            toast:
              "!bg-surface-elevated !border-border !text-fg !rounded-card !shadow-elevated",
            description: "!text-fg-secondary",
          },
        }}
      />
    </QueryClientProvider>
  );
}
