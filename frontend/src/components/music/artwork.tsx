"use client";

import Image from "next/image";
import { useState } from "react";

import { cn, hashString } from "@/lib/utils";

// Dark, desaturated bases with one luminous accent each: on-brand next to the lime.
const PALETTES: [string, string, string][] = [
  ["#1f2a1b", "#3d5a2a", "#d7f36a"],
  ["#1b2330", "#2d4a63", "#82b8d9"],
  ["#2a1f2b", "#5a2d4f", "#e77bb8"],
  ["#2b241b", "#634a2d", "#e8b96a"],
  ["#1b2b28", "#2d635a", "#7be7c9"],
  ["#241b2b", "#452d63", "#b49bf0"],
  ["#2b1d1b", "#63302d", "#e77b78"],
  ["#1d2421", "#3f4f45", "#c9d7a8"],
];

/**
 * Deterministic generated cover: the same seed always gives the same art. Used when a track has
 * no Cover Art Archive image (or it fails to load), and for artists, moods and playlists.
 */
export function GeneratedCover({
  seed,
  label,
  round = false,
  className,
}: {
  seed: string;
  label?: string;
  /** Shown in a circle (artists): the initials are centred so the circle cannot clip them. */
  round?: boolean;
  className?: string;
}) {
  const hash = hashString(seed);
  const [base, mid, glow] = PALETTES[hash % PALETTES.length];
  const angle = hash % 360;
  const x = 20 + ((hash >> 8) % 60);
  const y = 20 + ((hash >> 16) % 60);
  const rings = 2 + ((hash >> 4) % 3);
  const initials = (label ?? "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("");
  return (
    <div
      aria-hidden
      className={cn("relative size-full overflow-hidden", className)}
      style={{
        background: `radial-gradient(circle at ${x}% ${y}%, ${glow}33 0%, transparent 45%), linear-gradient(${angle}deg, ${base}, ${mid})`,
      }}
    >
      <svg
        viewBox="0 0 100 100"
        className="absolute inset-0 size-full opacity-40"
      >
        {Array.from({ length: rings }, (_, i) => (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={18 + i * 16}
            fill="none"
            stroke={glow}
            strokeOpacity={0.35 - i * 0.08}
            strokeWidth={0.6}
          />
        ))}
      </svg>
      {initials ? (
        <span
          className={cn(
            "absolute font-display",
            round ? "inset-0 grid place-items-center" : "bottom-[8%] left-[9%]",
          )}
        >
          <span className="font-display text-[clamp(0.75rem,18cqw,2.5rem)] leading-none font-bold text-white/85">
            {initials}
          </span>
        </span>
      ) : null}
    </div>
  );
}

/** Album artwork when known (Cover Art Archive via the image optimizer), else a generated cover. */
export function TrackArtwork({
  src,
  seed,
  label,
  alt,
  sizes = "200px",
  className,
  priority = false,
  round = false,
}: {
  src?: string | null;
  seed: string;
  label?: string;
  round?: boolean;
  alt: string;
  sizes?: string;
  className?: string;
  priority?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <div
      className={cn(
        "@container relative aspect-square overflow-hidden rounded-button bg-surface",
        round && "rounded-full",
        className,
      )}
    >
      {/* The generated cover sits underneath: it shows while the image loads, and instead of
          it when there is none or it fails. */}
      <GeneratedCover seed={seed} label={label} round={round} />
      {src && !failed ? (
        <Image
          src={src}
          alt={alt}
          fill
          sizes={sizes}
          priority={priority}
          className="object-cover"
          onError={() => setFailed(true)}
        />
      ) : null}
    </div>
  );
}

/** Four covers in a 2x2 grid for playlists; generated art when there are none. */
export function CollageArtwork({
  urls,
  seed,
  label,
  className,
}: {
  urls: string[];
  seed: string;
  label: string;
  className?: string;
}) {
  // Several tracks of one album share a cover: show four different ones, or a single cover.
  const covers = [...new Set(urls)];
  if (covers.length < 4) {
    return (
      <TrackArtwork
        src={covers[0]}
        seed={seed}
        label={label}
        alt=""
        className={className}
      />
    );
  }
  return (
    <div
      className={cn(
        "grid aspect-square grid-cols-2 overflow-hidden rounded-button",
        className,
      )}
    >
      {covers.slice(0, 4).map((url, i) => (
        <TrackArtwork
          key={url}
          src={url}
          seed={`${seed}-${i}`}
          alt=""
          className="rounded-none"
          sizes="100px"
        />
      ))}
    </div>
  );
}
