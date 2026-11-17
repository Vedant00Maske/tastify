"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Recent search terms, kept only in this browser (a per-viewer convenience, never sent to the
 * API). Storage can be unavailable (private mode, blocked site data), so every access is guarded
 * and the feature degrades to "no recent searches".
 */
const KEY = "tastify:recent-searches";
const MAX = 8;
const listeners = new Set<() => void>();
let cache: string[] | null = null;

function read(): string[] {
  if (cache) return cache;
  try {
    const parsed: unknown = JSON.parse(
      window.localStorage.getItem(KEY) ?? "[]",
    );
    cache = Array.isArray(parsed)
      ? parsed.filter((x): x is string => typeof x === "string").slice(0, MAX)
      : [];
  } catch {
    cache = [];
  }
  return cache;
}

function write(terms: string[]) {
  cache = terms;
  try {
    window.localStorage.setItem(KEY, JSON.stringify(terms));
  } catch {
    // Not persisted; still shown for this session.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const EMPTY: string[] = [];

export function useRecentSearches() {
  const terms = useSyncExternalStore(subscribe, read, () => EMPTY);
  const add = useCallback((term: string) => {
    const clean = term.trim();
    if (clean.length < 2) return;
    write(
      [
        clean,
        ...read().filter((t) => t.toLowerCase() !== clean.toLowerCase()),
      ].slice(0, MAX),
    );
  }, []);
  const remove = useCallback(
    (term: string) => write(read().filter((t) => t !== term)),
    [],
  );
  const clear = useCallback(() => write([]), []);
  return { terms, add, remove, clear };
}
