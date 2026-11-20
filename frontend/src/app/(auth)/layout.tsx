import type { ReactNode } from "react";

import { GeneratedCover } from "@/components/music/artwork";

/** Split layout: atmospheric art and the brand statement on the left, the form on the right. */
export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden overflow-hidden lg:block">
        <div className="absolute inset-0 grid grid-cols-3 grid-rows-3 gap-3 p-3 opacity-90">
          {[
            "dusk",
            "neon",
            "tape",
            "vinyl",
            "echo",
            "drift",
            "static",
            "bloom",
            "night",
          ].map((seed) => (
            <div key={seed} className="overflow-hidden rounded-card-lg">
              <GeneratedCover seed={`auth-${seed}`} />
            </div>
          ))}
        </div>
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/40 to-background/10" />
        <div className="absolute right-12 bottom-12 left-12">
          <p className="font-display text-hero font-bold">
            Music that knows you,
            <br />
            and <span className="text-accent">surprises you.</span>
          </p>
          <p className="mt-4 max-w-md text-fg-secondary">
            SONIQUEO learns your taste from what you play, like and skip, and
            explains every recommendation it makes.
          </p>
        </div>
      </div>
      <main className="flex items-center justify-center px-4 py-12 sm:px-8">
        {children}
      </main>
    </div>
  );
}
