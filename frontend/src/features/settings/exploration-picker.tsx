"use client";

import { Compass, Heart, Sparkles, Wand2 } from "lucide-react";

import { Slider } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";
import type { ExplorationMode } from "@/types/api";

export const MODES: {
  mode: ExplorationMode;
  label: string;
  detail: string;
  share: string;
}[] = [
  {
    mode: "familiar",
    label: "Familiar favourites",
    detail: "Mostly artists you already love",
    share: "80% familiar · 20% new",
  },
  {
    mode: "balanced",
    label: "Balanced",
    detail: "Half favourites, half discoveries",
    share: "50% familiar · 50% new",
  },
  {
    mode: "explorer",
    label: "Unexpected discoveries",
    detail: "Mostly artists new to you",
    share: "20% familiar · 80% new",
  },
];

/**
 * Familiarity versus exploration: three composition targets on a slider, or "learn it from my
 * listening" (null), stored as the user's exploration mode.
 */
export function ExplorationPicker({
  value,
  onChange,
}: {
  value: ExplorationMode | null;
  onChange: (value: ExplorationMode | null) => void;
}) {
  const index = value ? MODES.findIndex((m) => m.mode === value) : 1;
  const current = MODES[index];
  return (
    <div className="flex flex-col gap-6">
      <div
        className={cn(
          "rounded-card-lg border border-border bg-surface p-5 transition-opacity",
          value === null && "opacity-50",
        )}
      >
        <div className="mb-4 flex items-center justify-between text-support font-semibold">
          <span className="inline-flex items-center gap-1.5 text-fg-secondary">
            <Heart className="size-4" /> Familiar favourites
          </span>
          <span className="inline-flex items-center gap-1.5 text-fg-secondary">
            Unexpected discoveries <Compass className="size-4" />
          </span>
        </div>
        <Slider
          label="Familiarity versus exploration"
          valueText={`${current.label}: ${current.share}`}
          min={0}
          max={2}
          step={1}
          value={[index]}
          onValueChange={([v]) => onChange(MODES[v]?.mode ?? "balanced")}
        />
        <div className="mt-4">
          <p className="font-display text-card font-bold text-accent">
            {value ? current.label : "Learned from you"}
          </p>
          <p className="text-support text-fg-secondary">
            {value
              ? `${current.detail} (${current.share})`
              : "SONIQUEO sets the balance from how widely you listen."}
          </p>
        </div>
      </div>
      <button
        type="button"
        aria-pressed={value === null}
        onClick={() => onChange(value === null ? "balanced" : null)}
        className={cn(
          "flex items-center gap-3 rounded-card border p-4 text-left transition-colors",
          value === null
            ? "border-accent bg-accent-muted"
            : "border-border bg-surface hover:bg-surface-hover",
        )}
      >
        {value === null ? (
          <Sparkles className="size-5 text-accent" />
        ) : (
          <Wand2 className="size-5 text-fg-secondary" />
        )}
        <span>
          <span className="block font-semibold">Let SONIQUEO learn it</span>
          <span className="block text-support text-fg-secondary">
            Use my listening to decide how many new artists to mix in.
          </span>
        </span>
      </button>
    </div>
  );
}
