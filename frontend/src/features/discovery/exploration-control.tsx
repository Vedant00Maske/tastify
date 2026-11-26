"use client";

import { motion } from "motion/react";
import Link from "next/link";
import { useId } from "react";
import { toast } from "sonner";

import { Skeleton } from "@/components/ui/states";
import { MODES } from "@/features/settings/exploration-picker";
import {
  toUpdate,
  usePreferences,
  useUpdatePreferences,
} from "@/features/taste-profile/queries";
import { springToggle } from "@/lib/motion";
import { cn } from "@/lib/utils";
import type { ExplorationMode } from "@/types/api";

/** Short labels for the segments; the accessible name is the full Settings wording. */
const SHORT: Record<ExplorationMode, string> = {
  familiar: "Familiar",
  balanced: "Balanced",
  explorer: "Discoveries",
};

const modeOf = (mode: string | null | undefined) =>
  MODES.find((m) => m.mode === mode);

/**
 * Familiar versus new, on Home: the same saved preference as Settings (the listener chose that a
 * change here is a change everywhere), so every change confirms with a toast and offers Undo.
 */
export function ExplorationControl({
  effectiveMode,
}: {
  /** The mode the engine used for the current mix (shown while the setting is learned). */
  effectiveMode?: string;
}) {
  const preferences = usePreferences();
  const update = useUpdatePreferences();
  const name = useId();

  if (preferences.isPending) {
    return <Skeleton className="h-12 w-full max-w-sm rounded-full" />;
  }
  if (!preferences.data) return null;
  const current = preferences.data;

  if (!current.personalization_enabled) {
    return (
      <p className="text-support text-fg-secondary">
        Personalization is off, so this mix is not tuned to you.{" "}
        <Link
          href="/settings#preferences"
          className="font-semibold text-fg underline-offset-4 hover:underline"
        >
          Turn it on in Settings
        </Link>
      </p>
    );
  }

  const saved = current.exploration_mode;
  const shown =
    update.isPending && update.variables
      ? update.variables.exploration_mode
      : saved;

  const save = (mode: ExplorationMode | null) => {
    if (mode === saved) return;
    const previous = saved;
    update.mutate(
      { ...toUpdate(current), exploration_mode: mode },
      {
        onSuccess: (next) =>
          toast("Saved to your preferences", {
            description: mode
              ? `${modeOf(mode)?.label} (${modeOf(mode)?.share}) for every mix from now on.`
              : "SONIQUEO will set the balance from how widely you listen.",
            action: {
              label: "Undo",
              onClick: () =>
                update.mutate({
                  ...toUpdate(next),
                  exploration_mode: previous,
                }),
            },
          }),
        onError: () =>
          toast.error("Could not save that setting.", {
            action: { label: "Retry", onClick: () => save(mode) },
          }),
      },
    );
  };

  const active = modeOf(shown);
  const learned = modeOf(effectiveMode);
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="sr-only">Familiar versus new</legend>
      <div className="grid max-w-sm grid-cols-3 gap-1 rounded-full border border-border bg-background-secondary p-1">
        {MODES.map((mode) => {
          const checked = shown === mode.mode;
          return (
            <label
              key={mode.mode}
              className={cn(
                "relative flex min-h-11 cursor-pointer items-center justify-center rounded-full px-2 text-sm font-semibold transition-colors duration-150 select-none",
                "has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-accent",
                checked ? "text-accent" : "text-fg-secondary hover:text-fg",
              )}
            >
              <input
                type="radio"
                name={name}
                value={mode.mode}
                checked={checked}
                onChange={() => save(mode.mode)}
                aria-label={mode.label}
                className="sr-only"
              />
              {checked ? (
                <motion.span
                  layoutId={`${name}-selected`}
                  transition={springToggle}
                  aria-hidden
                  className="absolute inset-0 rounded-full border border-accent/40 bg-accent-muted"
                />
              ) : null}
              <span className="relative">{SHORT[mode.mode]}</span>
            </label>
          );
        })}
      </div>
      <p className="text-support text-fg-secondary">
        {active ? (
          <>
            <span className="tabular-nums">{active.share}</span>
            <span aria-hidden> · </span>
            <button
              type="button"
              onClick={() => save(null)}
              className="font-semibold text-fg-secondary underline-offset-4 hover:text-fg hover:underline"
            >
              Let SONIQUEO learn it
            </button>
          </>
        ) : (
          <>
            Learned from you
            {learned ? (
              <>
                {" "}
                · currently <span className="text-fg">{learned.label}</span>
              </>
            ) : null}
          </>
        )}
      </p>
    </fieldset>
  );
}
