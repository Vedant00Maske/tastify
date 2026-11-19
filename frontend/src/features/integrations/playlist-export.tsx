"use client";

import { ExternalLink, Share2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/primitives";
import { Spinner } from "@/components/ui/states";
import type { PlaylistExport } from "@/types/api";

import { errorText } from "./connections-panel";
import {
  useExportPlaylist,
  useIntegrations,
  usePlaylistExports,
} from "./queries";

function exportSummary(item: PlaylistExport): string {
  if (item.status === "failed")
    return `Export failed: ${item.error ?? "unknown error"}`;
  if (item.status === "running") return "Exporting…";
  const missing = item.unmatched ? `, ${item.unmatched} not found there` : "";
  return `${item.exported} ${item.exported === 1 ? "track" : "tracks"}${missing}`;
}

/** "Export" menu and the status of earlier exports, on a playlist page. */
export function PlaylistExport({
  playlistId,
  trackCount,
}: {
  playlistId: string;
  trackCount: number;
}) {
  const integrations = useIntegrations();
  const exports = usePlaylistExports(playlistId);
  const run = useExportPlaylist(playlistId);
  const targets = (integrations.data?.providers ?? []).filter((p) =>
    p.capabilities.includes("export_playlist"),
  );
  const connected = targets.filter((p) => p.connection?.status === "active");
  const done = exports.data?.exports ?? [];
  const nameOf = (provider: string) =>
    targets.find((t) => t.provider === provider)?.name ?? provider;

  const start = (provider: string) =>
    run.mutate(provider, {
      onSuccess: (result) =>
        toast.success(`Exported to ${nameOf(provider)}`, {
          description: exportSummary(result),
          action: result.external_url
            ? {
                label: "Open",
                onClick: () =>
                  window.open(result.external_url ?? "", "_blank", "noopener"),
              }
            : undefined,
        }),
      onError: (error) => toast.error(errorText(error)),
    });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            size="lg"
            variant="secondary"
            disabled={!trackCount || run.isPending}
          >
            {run.isPending ? <Spinner /> : <Share2 />} Export
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuLabel>Export to</DropdownMenuLabel>
          {connected.map((provider) => {
            const previous = done.find((d) => d.provider === provider.provider);
            const capped = trackCount > provider.max_export_tracks;
            return (
              <DropdownMenuItem
                key={provider.provider}
                onSelect={() => start(provider.provider)}
              >
                {provider.name}
                {previous ? " (update)" : ""}
                {capped ? ` · first ${provider.max_export_tracks}` : ""}
              </DropdownMenuItem>
            );
          })}
          {connected.length ? <DropdownMenuSeparator /> : null}
          <DropdownMenuItem asChild>
            <Link href="/settings#connections">
              {connected.length ? "Manage services" : "Connect a service"}
            </Link>
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {done.length ? (
        <ul
          aria-label="Exports"
          className="flex w-full flex-wrap gap-x-4 gap-y-1 text-support text-fg-secondary"
        >
          {done.map((item) => (
            <li
              key={item.provider}
              className="inline-flex items-center gap-1.5"
            >
              <span className="font-semibold text-fg">
                {nameOf(item.provider)}:
              </span>
              {exportSummary(item)}
              {item.external_url ? (
                <a
                  href={item.external_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-0.5 text-accent hover:underline"
                >
                  Open <ExternalLink className="size-3.5" aria-hidden />
                  <span className="sr-only">
                    on {nameOf(item.provider)} (new tab)
                  </span>
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  );
}
