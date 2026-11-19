"use client";

import { WifiOff } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";

import { useOnlineStatus } from "@/hooks/use-online-status";

/**
 * Shown on every page while the browser is offline. Queries pause instead of failing, and
 * feedback or playlist changes made meanwhile are sent when the connection returns
 * (TanStack Query's online network mode).
 */
export function OfflineBanner() {
  const online = useOnlineStatus();
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 top-3 z-[60] flex justify-center px-4"
    >
      <AnimatePresence>
        {online ? null : (
          <motion.p
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.2 }}
            className="pointer-events-auto flex items-center gap-2 rounded-full border border-warning/40 bg-surface-elevated px-4 py-2 text-support shadow-elevated"
          >
            <WifiOff className="size-4 text-warning" aria-hidden />
            You are offline. Changes are saved when you reconnect.
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
